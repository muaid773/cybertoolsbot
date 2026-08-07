import psycopg2
from tabulate import tabulate
import os

# إعداد الاتصال
DB_CONFIG = {
    "host": "",
    "database": "postgres",
    "user": "",
    "password": "",
    "port": 0000,
    "sslmode": "require"
}


# حدود الحماية
MAX_TABLES = 50
MAX_ROWS = 10


def run_query(cur, query, params=None):
    cur.execute(query, params or ())
    return cur.fetchall()


def main():

    print("\n========== DATABASE SECURITY REPORT ==========\n")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # معلومات القاعدة
    print("📌 معلومات الاتصال:")

    info = run_query(cur, """
        SELECT 
            current_database(),
            current_user,
            version()
    """)

    print(tabulate(
        info,
        headers=["Database", "User", "PostgreSQL Version"],
        tablefmt="grid"
    ))


    # عدد الجداول
    print("\n📌 الجداول:")

    tables = run_query(cur, """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
        LIMIT %s
    """, (MAX_TABLES,))


    print(tabulate(
        tables,
        headers=["Table"],
        tablefmt="grid"
    ))


    # تفاصيل الجداول
    for table in tables:

        table_name = table[0]

        print("\n================================")
        print("📂 TABLE:", table_name)

        # الأعمدة
        columns = run_query(cur, """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name=%s
        """, (table_name,))


        print("\nColumns:")
        print(tabulate(
            columns,
            headers=["Column", "Type"],
            tablefmt="grid"
        ))


        # عدد الصفوف بشكل آمن
        count = run_query(cur, f"""
            SELECT COUNT(*)
            FROM "{table_name}"
        """)

        print("\nRows:")
        print(count[0][0])


        # عينة بيانات فقط
        print("\nSample Data LIMIT", MAX_ROWS)

        sample = run_query(cur, f"""
            SELECT *
            FROM "{table_name}"
            LIMIT {MAX_ROWS}
        """)


        if sample:
            headers = [desc[0] for desc in cur.description]

            print(tabulate(
                sample,
                headers=headers,
                tablefmt="grid"
            ))


    # المستخدمين
    print("\n================================")
    print("👤 DATABASE USERS")

    users = run_query(cur, """
        SELECT usename
        FROM pg_user
    """)


    print(tabulate(
        users,
        headers=["Username"],
        tablefmt="grid"
    ))


    # الصلاحيات
    print("\n================================")
    print("🔐 CURRENT USER PRIVILEGES")

    privileges = run_query(cur, """
        SELECT *
        FROM information_schema.role_table_grants
        WHERE grantee=current_user
        LIMIT 100
    """)


    if privileges:
        print(tabulate(
            privileges,
            tablefmt="grid"
        ))
    else:
        print("No extra privileges found")


    cur.close()
    conn.close()

    print("\n✅ Report Finished")


if __name__ == "__main__":
    main()