"""
Create a test bookstore database and a QA dataset for DSPy prompt optimization.

Schema mirrors Simon Willison's research setup:
  - authors (id, name)
  - books (id, title, author_id, price)
  - customers (id, name, email)
  - orders (id, customer_id, order_date, status)
  - order_items (id, order_id, book_id, quantity, unit_price)
"""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "bookstore.db"
QA_PATH = Path(__file__).parent / "qa_dataset.json"


def create_database():
    """Create SQLite bookstore database with sample data."""
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Schema
    cur.executescript("""
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            author_id INTEGER REFERENCES authors(id),
            price REAL NOT NULL
        );

        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT
        );

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(id),
            order_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed'
        );

        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id),
            book_id INTEGER REFERENCES books(id),
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL
        );
    """)

    # Sample data
    authors = [
        (1, "金庸"),
        (2, "村上春樹"),
        (3, "J.K. Rowling"),
        (4, "George Orwell"),
        (5, "Isaac Asimov"),
    ]
    cur.executemany("INSERT INTO authors VALUES (?, ?)", authors)

    books = [
        (1, "射鵰英雄傳", 1, 380.0),
        (2, "神鵰俠侶", 1, 420.0),
        (3, "挪威的森林", 2, 350.0),
        (4, "1Q84", 2, 450.0),
        (5, "Harry Potter and the Philosopher's Stone", 3, 320.0),
        (6, "Harry Potter and the Chamber of Secrets", 3, 340.0),
        (7, "1984", 4, 280.0),
        (8, "Animal Farm", 4, 250.0),
        (9, "Foundation", 5, 300.0),
        (10, "I, Robot", 5, 290.0),
    ]
    cur.executemany("INSERT INTO books VALUES (?, ?, ?, ?)", books)

    customers = [
        (1, "王小明", "wang@example.com"),
        (2, "李大華", "lee@example.com"),
        (3, "張美麗", "chang@example.com"),
        (4, "陳建國", "chen@example.com"),
        (5, "林小芬", None),
    ]
    cur.executemany("INSERT INTO customers VALUES (?, ?, ?)", customers)

    orders = [
        (1, 1, "2024-01-15", "completed"),
        (2, 1, "2024-02-20", "completed"),
        (3, 2, "2024-03-10", "completed"),
        (4, 2, "2024-04-05", "cancelled"),
        (5, 3, "2024-05-01", "completed"),
        (6, 3, "2024-06-15", "completed"),
        (7, 4, "2024-07-20", "completed"),
        (8, 5, "2024-08-10", "completed"),
        (9, 1, "2024-09-05", "completed"),
        (10, 2, "2024-10-01", "completed"),
    ]
    cur.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)

    order_items = [
        # Order 1: 王小明 buys 射鵰 + 神鵰
        (1, 1, 1, 1, 380.0),
        (2, 1, 2, 1, 420.0),
        # Order 2: 王小明 buys 1984 x2
        (3, 2, 7, 2, 280.0),
        # Order 3: 李大華 buys Harry Potter 1 + Foundation
        (4, 3, 5, 1, 320.0),
        (5, 3, 9, 1, 300.0),
        # Order 4: 李大華 (cancelled) 1Q84
        (6, 4, 4, 1, 450.0),
        # Order 5: 張美麗 buys 挪威的森林 + Animal Farm
        (7, 5, 3, 1, 350.0),
        (8, 5, 8, 1, 250.0),
        # Order 6: 張美麗 buys Harry Potter 1,2
        (9, 6, 5, 1, 320.0),
        (10, 6, 6, 1, 340.0),
        # Order 7: 陳建國 buys Foundation x3 + I,Robot
        (11, 7, 9, 3, 300.0),
        (12, 7, 10, 1, 290.0),
        # Order 8: 林小芬 buys 1984 + Animal Farm
        (13, 8, 7, 1, 280.0),
        (14, 8, 8, 1, 250.0),
        # Order 9: 王小明 buys I,Robot
        (15, 9, 10, 1, 290.0),
        # Order 10: 李大華 buys 射鵰 + 神鵰 + 挪威
        (16, 10, 1, 1, 380.0),
        (17, 10, 2, 1, 420.0),
        (18, 10, 3, 1, 350.0),
    ]
    cur.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", order_items)

    conn.commit()
    conn.close()


def create_qa_dataset():
    """Create QA dataset with natural-language questions and gold SQL answers."""
    questions = [
        {
            "question": "總共有幾位作者？",
            "sql": "SELECT COUNT(*) FROM authors",
            "answer": "5",
        },
        {
            "question": "總共有幾本書？",
            "sql": "SELECT COUNT(*) FROM books",
            "answer": "10",
        },
        {
            "question": "最貴的書是哪一本？多少錢？",
            "sql": "SELECT title, price FROM books ORDER BY price DESC LIMIT 1",
            "answer": "1Q84, 450.0",
        },
        {
            "question": "金庸寫了哪幾本書？",
            "sql": "SELECT b.title FROM books b JOIN authors a ON b.author_id = a.id WHERE a.name = '金庸'",
            "answer": "射鵰英雄傳, 神鵰俠侶",
        },
        {
            "question": "哪個作者寫的書最多？",
            "sql": "SELECT a.name, COUNT(*) as cnt FROM authors a JOIN books b ON a.id = b.author_id GROUP BY a.id ORDER BY cnt DESC LIMIT 1",
            "answer": "金庸, 2",
        },
        {
            "question": "列出所有書名和價格，按價格從低到高排序",
            "sql": "SELECT title, price FROM books ORDER BY price ASC",
            "answer": None,  # verification: all 10 books, sorted by price
        },
        {
            "question": "價格在 300 元以上的書有哪些？",
            "sql": "SELECT title, price FROM books WHERE price > 300 ORDER BY price DESC",
            "answer": None,
        },
        {
            "question": "王小明總共花了多少錢買書？",
            "sql": "SELECT SUM(oi.quantity * oi.unit_price) FROM order_items oi JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id WHERE c.name = '王小明' AND o.status = 'completed'",
            "answer": "1640.0",
        },
        {
            "question": "哪個顧客花最多錢？花了多少？",
            "sql": "SELECT c.name, SUM(oi.quantity * oi.unit_price) as total FROM order_items oi JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id WHERE o.status = 'completed' GROUP BY c.id ORDER BY total DESC LIMIT 1",
            "answer": "張美麗, 1260.0",
        },
        {
            "question": "有多少訂單被取消了？",
            "sql": "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'",
            "answer": "1",
        },
        {
            "question": "列出所有完成訂單的編號和對應顧客名稱",
            "sql": "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'completed' ORDER BY o.id",
            "answer": None,
        },
        {
            "question": "哪一本書賣得最好（總銷量最多）？賣了幾本？",
            "sql": "SELECT b.title, SUM(oi.quantity) as total FROM order_items oi JOIN books b ON oi.book_id = b.id JOIN orders o ON oi.order_id = o.id WHERE o.status = 'completed' GROUP BY b.id ORDER BY total DESC LIMIT 1",
            "answer": "Foundation, 4",
        },
        {
            "question": "王小明買過哪幾本書？",
            "sql": "SELECT DISTINCT b.title FROM order_items oi JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id JOIN books b ON oi.book_id = b.id WHERE c.name = '王小明' AND o.status = 'completed'",
            "answer": "射鵰英雄傳, 神鵰俠侶, 1984, I, Robot",
        },
        {
            "question": "哪本書從來沒有被買過？",
            "sql": "SELECT b.title FROM books b LEFT JOIN order_items oi ON b.id = oi.book_id LEFT JOIN orders o ON oi.order_id = o.id AND o.status = 'completed' WHERE oi.id IS NULL",
            "answer": "0",
        },
        {
            "question": "Harry Potter 系列的書總共賣了多少本？",
            "sql": "SELECT SUM(oi.quantity) FROM order_items oi JOIN books b ON oi.book_id = b.id JOIN orders o ON oi.order_id = o.id WHERE b.title LIKE 'Harry Potter%' AND o.status = 'completed'",
            "answer": "3",
        },
        {
            "question": "列出所有顧客的名字和 email（包括沒有 email 的）",
            "sql": "SELECT name, COALESCE(email, '無') FROM customers ORDER BY name",
            "answer": None,
        },
        {
            "question": "2024 年第一季（1-3 月）有幾筆完成訂單？",
            "sql": "SELECT COUNT(*) FROM orders WHERE order_date BETWEEN '2024-01-01' AND '2024-03-31' AND status = 'completed'",
            "answer": "3",
        },
        {
            "question": "哪個月份訂單最多？幾筆？",
            "sql": "SELECT SUBSTR(order_date, 6, 2) as month, COUNT(*) as cnt FROM orders WHERE status = 'completed' GROUP BY month ORDER BY cnt DESC LIMIT 1",
            "answer": "10, 2",
        },
        {
            "question": "George Orwell 的書總共賣了多少錢？",
            "sql": "SELECT SUM(oi.quantity * oi.unit_price) FROM order_items oi JOIN books b ON oi.book_id = b.id JOIN authors a ON b.author_id = a.id JOIN orders o ON oi.order_id = o.id WHERE a.name = 'George Orwell' AND o.status = 'completed'",
            "answer": "1090.0",
        },
        {
            "question": "有多少顧客買過村上春樹的書？",
            "sql": "SELECT COUNT(DISTINCT o.customer_id) FROM order_items oi JOIN books b ON oi.book_id = b.id JOIN authors a ON b.author_id = a.id JOIN orders o ON oi.order_id = o.id WHERE a.name = '村上春樹' AND o.status = 'completed'",
            "answer": "2",
        },
        {
            "question": "列出所有書的作者名字和書名",
            "sql": "SELECT a.name, b.title FROM books b JOIN authors a ON b.author_id = a.id ORDER BY a.name, b.title",
            "answer": None,
        },
        {
            "question": "平均一本書多少錢？",
            "sql": "SELECT ROUND(AVG(price), 2) FROM books",
            "answer": "338.0",
        },
        {
            "question": "有 email 的顧客和有幾位？沒有 email 的有幾位？",
            "sql": "SELECT CASE WHEN email IS NULL THEN '無 email' ELSE '有 email' END, COUNT(*) FROM customers GROUP BY 1",
            "answer": None,
        },
        {
            "question": "哪個出版社...不是，哪個作者書的平均價格最高？",
            "sql": "SELECT a.name, ROUND(AVG(b.price), 2) FROM books b JOIN authors a ON b.author_id = a.id GROUP BY a.id ORDER BY AVG(b.price) DESC LIMIT 1",
            "answer": "金庸, 400.0",
        },
        {
            "question": "張美麗買過哪些書？花了多少錢？",
            "sql": "SELECT b.title, oi.quantity * oi.unit_price as subtotal FROM order_items oi JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id JOIN books b ON oi.book_id = b.id WHERE c.name = '張美麗' AND o.status = 'completed' ORDER BY o.id",
            "answer": None,
        },
        {
            "question": "哪個顧客訂單數量最多？幾筆？（只算完成訂單）",
            "sql": "SELECT c.name, COUNT(*) as cnt FROM orders o JOIN customers c ON o.customer_id = c.id WHERE o.status = 'completed' GROUP BY c.id ORDER BY cnt DESC LIMIT 1",
            "answer": "王小明, 3",
        },
        {
            "question": "Foundation 這本書有哪些顧客買過？",
            "sql": "SELECT DISTINCT c.name FROM order_items oi JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id JOIN books b ON oi.book_id = b.id WHERE b.title = 'Foundation' AND o.status = 'completed'",
            "answer": "李大華, 陳建國",
        },
        {
            "question": "價格低於 300 元的書有幾本？列出書名",
            "sql": "SELECT title, price FROM books WHERE price < 300 ORDER BY price",
            "answer": None,
        },
        {
            "question": "總共有幾筆訂單？（包含取消的）",
            "sql": "SELECT COUNT(*) FROM orders",
            "answer": "10",
        },
        {
            "question": "列出所有書名，以及每本書被購買的總次數，沒被買過的顯示 0",
            "sql": "SELECT b.title, COUNT(oi.id) as times_bought FROM books b LEFT JOIN order_items oi ON b.id = oi.book_id LEFT JOIN orders o ON oi.order_id = o.id AND o.status = 'completed' GROUP BY b.id ORDER BY times_bought DESC, b.title",
            "answer": None,
        },
    ]

    with open(QA_PATH, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)

    print(f"QA dataset written to {QA_PATH} ({len(questions)} questions)")


if __name__ == "__main__":
    create_database()
    create_qa_dataset()
    print(f"Database created at {DB_PATH}")
    print("Done.")
