"""Recursive-descent / Pratt parser for Excel formulas.

Parses formula text (WITHOUT leading '=') into an AST of frozen dataclasses.
Uses a single-pass regex tokenizer for performance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

from xlsx_core.ast import (
    BinaryOp,
    BoolLiteral,
    CellRef,
    DefinedName,
    EmptyArg,
    ErrorLiteral,
    Expr,
    FuncCall,
    NumberLiteral,
    RangeRef,
    StringLiteral,
    UnaryOp,
    _col_from_letters,
)

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TokenType(Enum):
    NUMBER = auto()
    STRING = auto()
    BOOL = auto()
    ERROR = auto()
    CELL_REF = auto()
    NAME = auto()
    OP = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    PERCENT = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    type: TokenType
    text: str
    col: int | None = None
    row: int | None = None
    col_abs: bool = False
    row_abs: bool = False
    sheet: str | None = None
    number: float | None = None


# Known function names
_KNOWN_FUNCTIONS: set[str] = {
    "SUM",
    "IF",
    "INT",
    "MIN",
    "AND",
    "MAX",
    "SUMIF",
    "IRR",
    "NPV",
    "AVERAGE",
    "PMT",
}

_RE_CELL_REF_PAT = re.compile(r"^\$?[A-Za-z]{1,3}\$?\d+$")

# Single-pass tokenizer regex. Order matters.
_RE_TOKEN = re.compile(
    r"""
    \s+                                    # whitespace (skip)
  | " ([^"]*?) "                           # string literal (group 1)
  | \#REF! | \#DIV/0! | \#VALUE!           # error literal
  | \#N/A | \#NAME\? | \#NULL! | \#NUM!    # more errors
  | ( TRUE | FALSE ) \b                    # boolean (group 2)
  | \d+(?:\.\d*)?(?:[eE][+-]?\d+)?        # number
  | ' [^']* ' ! \$?[A-Za-z]{1,3}\$?\d+   # quoted-sheet cell ref
  | \$?[A-Za-z]{1,3}\$?\d+                # cell reference
  | [A-Za-z_\u0080-\uffff][\w.\u0080-\uffff]*   # name
  | <= | >= | <>                           # multi-char ops
  | [!:]                                    # sheet-bang / range-colon
  | [+\-*/^&()=,<>%]                      # single-char ops/punctuation
""",
    re.VERBOSE | re.UNICODE,
)


def tokenize(formula: str) -> list[Token]:
    """Tokenize a formula string into a list of tokens in a single pass."""
    tokens: list[Token] = []
    pos = 0

    for m in _RE_TOKEN.finditer(formula):
        if m.start() != pos:
            gap = formula[pos : m.start()]
            if gap.strip():
                raise ParseError(f"Unrecognized token at pos {pos}: {gap!r}")
            pos = m.end()
            continue

        pos = m.end()
        text = m.group(0)

        # Skip whitespace
        if text.isspace():
            continue

        # String
        if text.startswith('"'):
            inner = m.group(1) if m.lastindex and m.group(1) is not None else text[1:-1]
            tokens.append(Token(TokenType.STRING, inner))
            continue

        # Error
        if text.startswith("#"):
            tokens.append(Token(TokenType.ERROR, text))
            continue

        # Boolean
        upper = text.upper()
        if upper in ("TRUE", "FALSE"):
            tokens.append(Token(TokenType.BOOL, text))
            continue

        # Number
        if text[0].isdigit():
            tokens.append(Token(TokenType.NUMBER, text, number=float(text)))
            continue

        # Multi-char ops
        if text in ("<=", ">=", "<>"):
            tokens.append(Token(TokenType.OP, text))
            continue

        # Sheet bang and range colon
        if text in ("!", ":"):
            tokens.append(Token(TokenType.OP, text))
            continue

        # Single-char ops and punctuation
        if text in ("+", "-", "*", "/", "^", "&", "=", "<", ">"):
            tokens.append(Token(TokenType.OP, text))
            continue
        if text == "(":
            tokens.append(Token(TokenType.LPAREN, "("))
            continue
        if text == ")":
            tokens.append(Token(TokenType.RPAREN, ")"))
            continue
        if text == ",":
            tokens.append(Token(TokenType.COMMA, ","))
            continue
        if text == "%":
            tokens.append(Token(TokenType.PERCENT, "%"))
            continue

        # Quoted sheet cell ref: 'Sheet Name'!A1
        if text.startswith("'"):
            # Parse: 'Sheet Name'!A1
            end_quote = text.index("'", 1)
            sheet_name = text[1:end_quote]
            cell_text = text[end_quote + 2 :]  # skip '!
            col_abs, col_str, row_abs, row_num = _parse_cell_ref_str(cell_text)
            if row_num > 0:
                tokens.append(
                    Token(
                        TokenType.CELL_REF,
                        cell_text,
                        col=_col_from_letters(col_str),
                        row=row_num - 1,
                        col_abs=col_abs,
                        row_abs=row_abs,
                        sheet=sheet_name,
                    )
                )
                continue

        # Cell reference
        if _RE_CELL_REF_PAT.match(text):
            col_abs, col_str, row_abs, row_num = _parse_cell_ref_str(text)
            if row_num > 0:
                tokens.append(
                    Token(
                        TokenType.CELL_REF,
                        text,
                        col=_col_from_letters(col_str),
                        row=row_num - 1,
                        col_abs=col_abs,
                        row_abs=row_abs,
                    )
                )
                continue

        # Name
        tokens.append(Token(TokenType.NAME, text))

    # Handle trailing gap
    if pos < len(formula):
        gap = formula[pos:].strip()
        if gap:
            raise ParseError(f"Unrecognized trailing token: {gap!r}")

    tokens.append(Token(TokenType.EOF, ""))
    return tokens


def _parse_cell_ref_str(text: str) -> tuple[bool, str, bool, int]:
    """Parse a cell reference like '$AB$123' into (col_abs, col_str, row_abs, row)."""
    col_abs = text[0] == "$"
    start = 1 if col_abs else 0
    col_end = start
    while col_end < len(text) and text[col_end].isalpha():
        col_end += 1
    col_str = text[start:col_end]
    row_abs = text[col_end] == "$" if col_end < len(text) else False
    row_start = col_end + 1 if row_abs else col_end
    row_num = int(text[row_start:])
    return col_abs, col_str, row_abs, row_num


# ---------------------------------------------------------------------------
# Pratt Parser
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Raised when a formula cannot be parsed."""

    pass


_PREC = {
    "=": 1,
    "<>": 1,
    "<": 1,
    ">": 1,
    "<=": 1,
    ">=": 1,
    "&": 2,
    "+": 3,
    "-": 3,
    "*": 4,
    "/": 4,
    "^": 5,
    "u-": 6,
    "u+": 6,
}


def parse(formula: str) -> Expr:
    """Parse a formula string (without leading '=') into an AST."""
    tokens = tokenize(formula)
    parser = _Parser(tokens)
    ast = parser.parse_expr(0)
    if parser.peek().type != TokenType.EOF:
        raise ParseError(
            f"Unexpected token after expression: {parser.peek().text!r} at {parser.pos}"
        )
    return ast


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def peek_ahead(self, n: int = 1) -> Token:
        idx = self.pos + n
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, ttype: TokenType) -> Token:
        t = self.peek()
        if t.type != ttype:
            raise ParseError(
                f"Expected {ttype}, got {t.type}: {t.text!r} at pos {self.pos}"
            )
        return self.advance()

    def parse_expr(self, min_prec: int) -> Expr:
        token = self.peek()
        left = self._nud(token)

        while True:
            token = self.peek()
            if token.type == TokenType.EOF:
                break
            if token.type == TokenType.OP:
                prec = _PREC.get(token.text, 0)
                if prec == 0:
                    # Not an infix operator — could be '!' (sheet bang) or ':' (range)
                    # These are handled in _nud, so just break
                    break
                if prec < min_prec:
                    break
                self.advance()
                next_min = prec if token.text == "^" else prec + 1
                right = self.parse_expr(next_min)
                left = BinaryOp(op=token.text, left=left, right=right)
            elif token.type == TokenType.PERCENT:
                if _PREC.get("u-", 0) < min_prec:
                    break
                self.advance()
                left = BinaryOp(op="/", left=left, right=NumberLiteral(value=100.0))
            elif token.type == TokenType.LPAREN:
                if _PREC.get("u-", 0) < min_prec:
                    break
                self.advance()
                args = self._parse_args()
                if isinstance(left, DefinedName):
                    left = FuncCall(name=left.name.upper(), args=args)
                else:
                    raise ParseError(
                        f"Cannot call non-name expression at pos {self.pos}"
                    )
            else:
                break

        return left

    def _nud(self, token: Token) -> Expr:
        if token.type == TokenType.NUMBER:
            self.advance()
            return NumberLiteral(value=token.number or 0.0)
        if token.type == TokenType.STRING:
            self.advance()
            return StringLiteral(value=token.text)
        if token.type == TokenType.BOOL:
            self.advance()
            return BoolLiteral(value=token.text.upper() == "TRUE")
        if token.type == TokenType.ERROR:
            self.advance()
            return ErrorLiteral(error=token.text)
        if token.type == TokenType.CELL_REF:
            return self._nud_cell_ref()
        if token.type == TokenType.NAME:
            return self._nud_name()
        if token.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_expr(0)
            self.expect(TokenType.RPAREN)
            return expr
        if token.type == TokenType.OP and token.text in "+-":
            self.advance()
            op = token.text
            precedence = _PREC[f"u{op}"]
            operand = self.parse_expr(precedence)
            return UnaryOp(op=op, operand=operand)
        if token.type == TokenType.COMMA:
            self.advance()
            return EmptyArg()
        raise ParseError(
            f"Unexpected token: {token.type} {token.text!r} at pos {self.pos}"
        )

    def _nud_cell_ref(self) -> Expr:
        token = self.advance()
        cr = CellRef(
            col=token.col or 0,
            row=token.row or 0,
            col_abs=token.col_abs,
            row_abs=token.row_abs,
            sheet=token.sheet,
        )
        # Check for range: A1:B2
        if self.peek().type == TokenType.OP and self.peek().text == ":":
            self.advance()  # ':'
            end = self._resolve_cell_or_sheet_cell()
            end = CellRef(
                col=end.col, row=end.row,
                col_abs=end.col_abs, row_abs=end.row_abs,
                sheet=end.sheet or cr.sheet,
            )
            return RangeRef(start=cr, end=end)
        return cr

    def _nud_name(self) -> Expr:
        token = self.advance()
        name = token.text
        # Check for sheet!cell pattern
        if self.peek().type == TokenType.OP and self.peek().text == "!":
            self.advance()  # consume '!'
            cell_token = self.peek()
            if cell_token.type == TokenType.ERROR:
                self.advance()
                return ErrorLiteral(error=cell_token.text)
            if cell_token.type != TokenType.CELL_REF:
                raise ParseError(
                    f"Expected cell ref after !, got {cell_token.type}"
                )
            self.advance()
            cr = CellRef(
                col=cell_token.col or 0,
                row=cell_token.row or 0,
                col_abs=cell_token.col_abs,
                row_abs=cell_token.row_abs,
                sheet=name,
            )
            # Check for range: sheet!A1:B2
            if self.peek().type == TokenType.OP and self.peek().text == ":":
                self.advance()
                end = self._resolve_cell_or_sheet_cell()
                end = CellRef(
                    col=end.col, row=end.row,
                    col_abs=end.col_abs, row_abs=end.row_abs,
                    sheet=end.sheet or cr.sheet,
                )
                return RangeRef(start=cr, end=end)
            return cr
        return DefinedName(name=name)

    def _resolve_cell_or_sheet_cell(self) -> CellRef:
        """Parse a cell reference, optionally sheet-qualified (for range endpoints)."""
        tx = self.peek()
        if tx.type == TokenType.NAME:
            # Could be a sheet name
            if self.peek_ahead().type == TokenType.OP and self.peek_ahead().text == "!":
                sheet_name = tx.text
                self.advance()  # name
                self.advance()  # '!'
                ct = self.expect(TokenType.CELL_REF)
                return CellRef(
                    col=ct.col or 0,
                    row=ct.row or 0,
                    col_abs=ct.col_abs,
                    row_abs=ct.row_abs,
                    sheet=sheet_name,
                )
            # It's a defined name used as a cell ref — could be an error?
            self.advance()
            return CellRef(col=0, row=0, col_abs=False, row_abs=False)
        ct = self.expect(TokenType.CELL_REF)
        return CellRef(
            col=ct.col or 0,
            row=ct.row or 0,
            col_abs=ct.col_abs,
            row_abs=ct.row_abs,
            sheet=ct.sheet,
        )

    def _parse_args(self) -> list[Expr]:
        args: list[Expr] = []
        if self.peek().type == TokenType.RPAREN:
            self.advance()
            return args
        while True:
            if self.peek().type == TokenType.COMMA:
                args.append(EmptyArg())
                self.advance()
                continue
            if self.peek().type == TokenType.RPAREN:
                self.advance()
                break
            args.append(self.parse_expr(0))
            if self.peek().type == TokenType.RPAREN:
                self.advance()
                break
            if self.peek().type == TokenType.COMMA:
                self.advance()
                continue
            if self.peek().type == TokenType.EOF:
                raise ParseError("Unclosed function arguments")
        return args


# ---------------------------------------------------------------------------
# R1C1 rendering
# ---------------------------------------------------------------------------


def to_r1c1(ast: Expr, anchor_col: int, anchor_row: int) -> str:
    """Convert AST to R1C1 notation relative to (anchor_col, anchor_row) — 0-based."""
    return _R1C1Renderer(anchor_col, anchor_row).render(ast)


class _R1C1Renderer:
    def __init__(self, anchor_col: int, anchor_row: int) -> None:
        self.ac = anchor_col
        self.ar = anchor_row

    def render(self, node: Expr) -> str:
        if isinstance(node, NumberLiteral):
            v = node.value
            if v == int(v) and abs(v) < 1e15:
                return str(int(v))
            return f"{v:.15g}"
        if isinstance(node, StringLiteral):
            return f'"{node.value}"'
        if isinstance(node, BoolLiteral):
            return "TRUE" if node.value else "FALSE"
        if isinstance(node, ErrorLiteral):
            return node.error
        if isinstance(node, EmptyArg):
            return ""
        if isinstance(node, CellRef):
            return node.to_r1c1(self.ac, self.ar)
        if isinstance(node, RangeRef):
            start = node.start.to_r1c1(self.ac, self.ar)
            end = node.end.to_r1c1(self.ac, self.ar)
            return f"{start}:{end}"
        if isinstance(node, DefinedName):
            return node.name
        if isinstance(node, UnaryOp):
            return f"{node.op}{self.render(node.operand)}"
        if isinstance(node, BinaryOp):
            left = self.render(node.left)
            right = self.render(node.right)
            return f"({left}{node.op}{right})"
        if isinstance(node, FuncCall):
            args = ",".join(self.render(a) for a in node.args)
            return f"{node.name}({args})"
        return "?"
