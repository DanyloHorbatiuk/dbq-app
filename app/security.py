"""SQL validation for the arbitrary-SQL path of POST /api/execute
(SPEC.md §ФВ-03).

This is defense *in depth* under the guarantee that actually matters —
saw_readonly's GRANT SELECT plus BEGIN READ ONLY in executor.py — not a
substitute for it. Its job is deciding whether client-submitted SQL text
is even worth sending to Postgres, using a hand-rolled tokenizer rather
than a naive ";".split(): CLAUDE.md explicitly calls this out, because a
semicolon can legally appear inside a string literal.

Deliberately NOT handling E'...' backslash escapes (only the plain ''
doubled-quote rule): skipping that only ever makes this scanner think a
string ends *earlier* than Postgres does, which can only make it see
*more* things as top-level SQL than there really are — i.e. it can only
become more likely to (safely) reject a query, never miss a real
statement separator hidden inside a string. A tokenizer that fails
closed doesn't need to be a complete SQL parser.
"""

from __future__ import annotations

_ALLOWED_START_KEYWORDS = {"select", "with", "table", "values", "explain"}

# EXPLAIN can legally prefix INSERT/UPDATE/DELETE/MERGE, and EXPLAIN
# ANALYZE actually *executes* the statement it wraps to measure it —
# allowing bare EXPLAIN without checking what follows would reopen
# exactly the write access READ ONLY + saw_readonly exist to close.
_ALLOWED_AFTER_EXPLAIN = {"select", "with", "table", "values"}


class SqlValidationError(ValueError):
    """Raised when submitted SQL fails a §ФВ-03 check. Always turned into
    an HTTP 400 with this message by the caller — never swallowed."""


def validate_readonly_sql(sql: str) -> str:
    """Returns the single validated statement (whitespace-trimmed), or
    raises SqlValidationError. Validates only — never rewrites the SQL."""
    statements = _split_statements(sql)
    if len(statements) == 0:
        raise SqlValidationError("Порожній запит.")
    if len(statements) > 1:
        raise SqlValidationError(
            "Дозволено лише один SQL-оператор за запит; знайдено декілька, "
            "розділених крапкою з комою поза рядковим літералом."
        )

    statement = statements[0]
    first_word, rest = _first_keyword(statement)
    if first_word is None or first_word not in _ALLOWED_START_KEYWORDS:
        raise SqlValidationError(
            "Запит має починатися з SELECT, WITH, TABLE, VALUES або EXPLAIN."
        )

    if first_word == "explain":
        inner = _skip_explain_options(rest)
        inner_word, _ = _first_keyword(inner)
        if inner_word is None or inner_word not in _ALLOWED_AFTER_EXPLAIN:
            raise SqlValidationError(
                "EXPLAIN дозволено лише для SELECT/WITH/TABLE/VALUES: "
                "EXPLAIN ANALYZE над INSERT/UPDATE/DELETE справді виконує "
                "цей оператор, а не лише планує його."
            )

    return statement


def _split_statements(sql: str) -> list[str]:
    """Walks the SQL text once, tracking whether we're inside a string,
    a quoted identifier, a dollar-quoted block, or a comment, and splits
    on ';' only when none of those apply."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        if ch == "'":
            j = _consume_simple_string(sql, i)
            buf.append(sql[i:j])
            i = j
            continue

        if ch == '"':
            j = _consume_quoted_ident(sql, i)
            buf.append(sql[i:j])
            i = j
            continue

        if ch == "$":
            tag_end = _dollar_tag_end(sql, i)
            if tag_end is not None:
                j = _consume_dollar_quoted(sql, i, tag_end)
                buf.append(sql[i:j])
                i = j
                continue

        if sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j + 1
            buf.append(sql[i:j])
            i = j
            continue

        if sql.startswith("/*", i):
            j = _consume_block_comment(sql, i)
            buf.append(sql[i:j])
            i = j
            continue

        if ch == ";":
            piece = "".join(buf).strip()
            if piece:
                statements.append(piece)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _consume_simple_string(sql: str, start: int) -> int:
    """start points at the opening '. '' is the only recognized escape
    (see the module docstring for why E'...' backslash escapes are
    deliberately not handled)."""
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == "'":
            if i + 1 < n and sql[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return n  # unterminated — let Postgres report the real syntax error


def _consume_quoted_ident(sql: str, start: int) -> int:
    """start points at the opening \". \"\" is the escape, same idea as
    single-quoted strings but there is no backslash-escaped variant for
    identifiers in PostgreSQL."""
    i = start + 1
    n = len(sql)
    while i < n:
        if sql[i] == '"':
            if i + 1 < n and sql[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _dollar_tag_end(sql: str, start: int) -> int | None:
    """start points at '$'. Returns the index just past a $tag$
    delimiter's closing '$' (tag may be empty, i.e. plain $$), or None
    if this '$' isn't actually opening a dollar-quoted block."""
    n = len(sql)
    j = start + 1
    while j < n and (sql[j].isalnum() or sql[j] == "_"):
        j += 1
    if j < n and sql[j] == "$":
        return j + 1
    return None


def _consume_dollar_quoted(sql: str, start: int, tag_end: int) -> int:
    tag = sql[start:tag_end]
    close = sql.find(tag, tag_end)
    return len(sql) if close == -1 else close + len(tag)


def _consume_block_comment(sql: str, start: int) -> int:
    """PostgreSQL nests /* */ comments, unlike standard SQL — depth has
    to be tracked, not just found the next '*/'."""
    depth = 1
    i = start + 2
    n = len(sql)
    while i < n and depth > 0:
        if sql.startswith("/*", i):
            depth += 1
            i += 2
        elif sql.startswith("*/", i):
            depth -= 1
            i += 2
        else:
            i += 1
    return i


def _first_keyword(statement: str) -> tuple[str | None, str]:
    """Skips leading whitespace/comments, then returns
    (lowercased first word, remainder after it)."""
    i = 0
    n = len(statement)
    while i < n:
        if statement[i].isspace():
            i += 1
            continue
        if statement.startswith("--", i):
            j = statement.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if statement.startswith("/*", i):
            i = _consume_block_comment(statement, i)
            continue
        break

    j = i
    while j < n and (statement[j].isalnum() or statement[j] == "_"):
        j += 1
    if j == i:
        return None, statement[i:]
    return statement[i:j].lower(), statement[j:]


def _skip_explain_options(rest: str) -> str:
    """Skips EXPLAIN's optional parenthesized option list, e.g.
    "(ANALYZE, BUFFERS)", to reach the statement it actually wraps."""
    i = 0
    n = len(rest)
    while i < n and rest[i].isspace():
        i += 1
    if i < n and rest[i] == "(":
        depth = 1
        i += 1
        while i < n and depth > 0:
            if rest[i] == "(":
                depth += 1
            elif rest[i] == ")":
                depth -= 1
            i += 1
    return rest[i:]
