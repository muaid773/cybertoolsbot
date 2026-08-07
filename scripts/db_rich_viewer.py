#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


console = Console()


@dataclass
class TableInfo:
    name: str
    columns: list[dict[str, Any]]
    row_count: int


def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetchall(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchall()


def fetchone(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    cur = conn.execute(sql, params)
    return cur.fetchone()


def get_tables(conn: sqlite3.Connection) -> list[str]:
    rows = fetchall(
        conn,
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """,
    )
    return [row["name"] for row in rows]


def get_table_info(conn: sqlite3.Connection, table_name: str) -> TableInfo:
    columns = fetchall(conn, f"PRAGMA table_info({table_name})")
    count_row = fetchone(conn, f"SELECT COUNT(*) AS cnt FROM {table_name}")
    row_count = int(count_row["cnt"]) if count_row else 0
    return TableInfo(name=table_name, columns=[dict(c) for c in columns], row_count=row_count)


def fmt_value(value: Any) -> str:
    if value is None:
        return "[dim]NULL[/dim]"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    text = str(value)
    if len(text) > 70:
        return text[:67] + "..."
    return text


def render_title(db_path: str, tables: list[str]) -> None:
    title = Text("SQLite Database Explorer", style="bold cyan")
    subtitle = Text(f"{db_path}  •  {len(tables)} tables", style="dim")
    console.print(Panel.fit(Text.assemble(title, "\n", subtitle), border_style="cyan"))


def render_overview(conn: sqlite3.Connection, infos: list[TableInfo]) -> None:
    t = Table(title="Overview", box=box.ROUNDED, show_lines=False)
    t.add_column("Table", style="bold")
    t.add_column("Rows", justify="right")
    t.add_column("Columns", justify="right")
    t.add_column("PK / Notes")

    for info in infos:
        pk_cols = [c["name"] for c in info.columns if c.get("pk")]
        notes = ", ".join(pk_cols) if pk_cols else "-"
        t.add_row(info.name, str(info.row_count), str(len(info.columns)), notes)

    console.print(t)


def render_schema(info: TableInfo) -> None:
    t = Table(
        title=f"Schema: {info.name}",
        box=box.SIMPLE_HEAVY,
        header_style="bold magenta",
        show_lines=False,
    )
    t.add_column("#", justify="right", style="dim")
    t.add_column("Name", style="bold")
    t.add_column("Type")
    t.add_column("PK", justify="center")
    t.add_column("Not Null", justify="center")
    t.add_column("Default")
    t.add_column("Notes")

    for idx, col in enumerate(info.columns, start=1):
        notes = []
        if col.get("pk"):
            notes.append("PRIMARY KEY")
        if col.get("name") == "telegram_id":
            notes.append("identifier")
        if col.get("unique"):
            notes.append("unique")
        t.add_row(
            str(idx),
            str(col.get("name", "")),
            str(col.get("type", "")),
            "✓" if col.get("pk") else "",
            "✓" if col.get("notnull") else "",
            fmt_value(col.get("dflt_value")),
            ", ".join(notes) if notes else "-",
        )

    console.print(t)


def render_sample_rows(conn: sqlite3.Connection, table_name: str, limit: int = 8) -> None:
    rows = fetchall(conn, f"SELECT * FROM {table_name} LIMIT ?", (limit,))
    if not rows:
        console.print(Panel.fit(f"[dim]No rows in {table_name}[/dim]", title=table_name))
        return

    t = Table(
        title=f"Sample rows: {table_name}",
        box=box.MINIMAL_DOUBLE_HEAD,
        header_style="bold green",
        show_lines=False,
        expand=True,
    )

    columns = rows[0].keys()
    for col in columns:
        t.add_column(col, overflow="fold")

    for row in rows:
        t.add_row(*[fmt_value(row[col]) for col in columns])

    console.print(t)


def render_users_with_counts(conn: sqlite3.Connection) -> None:
    rows = fetchall(
        conn,
        """
        SELECT
            u.telegram_id,
            u.username,
            u.first_name,
            u.points,
            u.uploaded_contacts,
            u.created_at,
            COUNT(uc.id) AS linked_contacts
        FROM users u
        LEFT JOIN user_contacts uc ON uc.user_id = u.telegram_id
        GROUP BY u.telegram_id
        ORDER BY u.points DESC, u.uploaded_contacts DESC, u.telegram_id ASC
        """,
    )

    t = Table(
        title="Users (smart view)",
        box=box.ROUNDED,
        header_style="bold cyan",
        expand=True,
    )
    t.add_column("telegram_id", justify="right")
    t.add_column("username")
    t.add_column("first_name")
    t.add_column("points", justify="right")
    t.add_column("uploaded", justify="right")
    t.add_column("linked", justify="right")
    t.add_column("created_at")

    for row in rows:
        t.add_row(
            fmt_value(row["telegram_id"]),
            fmt_value(row["username"]),
            fmt_value(row["first_name"]),
            fmt_value(row["points"]),
            fmt_value(row["uploaded_contacts"]),
            fmt_value(row["linked_contacts"]),
            fmt_value(row["created_at"]),
        )

    console.print(t)


def render_contacts_with_names(conn: sqlite3.Connection) -> None:
    rows = fetchall(
        conn,
        """
        SELECT
            c.id,
            c.phone,
            c.created_at,
            COUNT(DISTINCT cn.id) AS names_count,
            COUNT(DISTINCT uc.id) AS owners_count
        FROM contacts c
        LEFT JOIN contact_names cn ON cn.contact_id = c.id
        LEFT JOIN user_contacts uc ON uc.contact_id = c.id
        GROUP BY c.id
        ORDER BY names_count DESC, owners_count DESC, c.id ASC
        """,
    )

    t = Table(
        title="Contacts (smart view)",
        box=box.ROUNDED,
        header_style="bold yellow",
        expand=True,
    )
    t.add_column("id", justify="right")
    t.add_column("phone")
    t.add_column("names", justify="right")
    t.add_column("owners", justify="right")
    t.add_column("created_at")

    for row in rows:
        t.add_row(
            fmt_value(row["id"]),
            fmt_value(row["phone"]),
            fmt_value(row["names_count"]),
            fmt_value(row["owners_count"]),
            fmt_value(row["created_at"]),
        )

    console.print(t)


def render_contact_names(conn: sqlite3.Connection, limit: int = 25) -> None:
    rows = fetchall(
        conn,
        """
        SELECT
            cn.id,
            cn.contact_id,
            c.phone,
            cn.name
        FROM contact_names cn
        JOIN contacts c ON c.id = cn.contact_id
        ORDER BY cn.contact_id ASC, cn.name ASC
        LIMIT ?
        """,
        (limit,),
    )

    t = Table(
        title=f"Contact names (first {limit})",
        box=box.SIMPLE_HEAVY,
        header_style="bold green",
        expand=True,
    )
    t.add_column("id", justify="right")
    t.add_column("contact_id", justify="right")
    t.add_column("phone")
    t.add_column("name")

    for row in rows:
        t.add_row(
            fmt_value(row["id"]),
            fmt_value(row["contact_id"]),
            fmt_value(row["phone"]),
            fmt_value(row["name"]),
        )

    console.print(t)


def render_links(conn: sqlite3.Connection, limit: int = 25) -> None:
    rows = fetchall(
        conn,
        """
        SELECT
            uc.id,
            uc.user_id,
            u.username,
            uc.contact_id,
            c.phone,
            uc.created_at
        FROM user_contacts uc
        JOIN users u ON u.telegram_id = uc.user_id
        JOIN contacts c ON c.id = uc.contact_id
        ORDER BY uc.created_at DESC, uc.id DESC
        LIMIT ?
        """,
        (limit,),
    )

    t = Table(
        title=f"User-Contact links (latest {limit})",
        box=box.SIMPLE_HEAVY,
        header_style="bold blue",
        expand=True,
    )
    t.add_column("id", justify="right")
    t.add_column("user_id", justify="right")
    t.add_column("username")
    t.add_column("contact_id", justify="right")
    t.add_column("phone")
    t.add_column("created_at")

    for row in rows:
        t.add_row(
            fmt_value(row["id"]),
            fmt_value(row["user_id"]),
            fmt_value(row["username"]),
            fmt_value(row["contact_id"]),
            fmt_value(row["phone"]),
            fmt_value(row["created_at"]),
        )

    console.print(t)


def render_relationship_summary(conn: sqlite3.Connection) -> None:
    stats = fetchone(
        conn,
        """
        SELECT
            (SELECT COUNT(*) FROM users) AS users_count,
            (SELECT COUNT(*) FROM contacts) AS contacts_count,
            (SELECT COUNT(*) FROM contact_names) AS names_count,
            (SELECT COUNT(*) FROM user_contacts) AS links_count,
            (SELECT COALESCE(MAX(points), 0) FROM users) AS max_points,
            (SELECT COALESCE(SUM(uploaded_contacts), 0) FROM users) AS sum_uploaded
        """,
    )

    t = Table(title="Relationship summary", box=box.ROUNDED, header_style="bold white")
    t.add_column("Metric")
    t.add_column("Value", justify="right")

    for key, label in [
        ("users_count", "Users"),
        ("contacts_count", "Contacts"),
        ("names_count", "Contact names"),
        ("links_count", "Links"),
        ("max_points", "Max points"),
        ("sum_uploaded", "Total uploaded"),
    ]:
        t.add_row(label, fmt_value(stats[key] if stats else None))

    console.print(t)


def inspect_database(db_path: str, sample_limit: int = 8, link_limit: int = 25) -> None:
    conn = connect_db(db_path)
    try:
        tables = get_tables(conn)
        infos = [get_table_info(conn, t) for t in tables]

        render_title(db_path, tables)
        render_overview(conn, infos)
        render_relationship_summary(conn)

        if "users" in tables:
            console.rule("[bold cyan]Users")
            render_users_with_counts(conn)
            render_schema(next(info for info in infos if info.name == "users"))
            render_sample_rows(conn, "users", sample_limit)

        if "contacts" in tables:
            console.rule("[bold yellow]Contacts")
            render_contacts_with_names(conn)
            render_schema(next(info for info in infos if info.name == "contacts"))
            render_sample_rows(conn, "contacts", sample_limit)

        if "contact_names" in tables:
            console.rule("[bold green]Contact Names")
            render_contact_names(conn, link_limit)
            render_schema(next(info for info in infos if info.name == "contact_names"))
            render_sample_rows(conn, "contact_names", sample_limit)

        if "user_contacts" in tables:
            console.rule("[bold blue]User Contacts")
            render_links(conn, link_limit)
            render_schema(next(info for info in infos if info.name == "user_contacts"))
            render_sample_rows(conn, "user_contacts", sample_limit)

        remaining = [i for i in infos if i.name not in {"users", "contacts", "contact_names", "user_contacts"}]
        if remaining:
            console.rule("[bold magenta]Other tables")
            for info in remaining:
                render_schema(info)
                render_sample_rows(conn, info.name, sample_limit)

    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart SQLite database viewer using Rich.")
    parser.add_argument(
        "db",
        nargs="?",
        default="db.sqlite3",
        help="Path to sqlite database file (default: db.sqlite3)",
    )
    parser.add_argument("--sample-limit", type=int, default=8, help="Number of sample rows to show per table.")
    parser.add_argument("--link-limit", type=int, default=25, help="Number of relation rows to show.")
    args = parser.parse_args()

    inspect_database(args.db, sample_limit=args.sample_limit, link_limit=args.link_limit)


if __name__ == "__main__":
    main()