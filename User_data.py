import sqlite3

def create_tables():
    conn = sqlite3.connect('User_data.db')
    cursor = conn.cursor()

    # ตาราง Vocabularies
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS Vocabularies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT NOT NULL,
        meaning TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # ตาราง common_errors
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS common_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_said TEXT NOT NULL,
        correct_version TEXT NOT NULL,
        explanation TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # ตาราง tasks
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            is_completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # ยืนยันการสร้างและปิดการเชื่อมต่อ
    conn.commit()
    conn.close()
    print("✅ สร้างตารางใน SQL เรียบร้อยแล้ว")

if __name__ == "__main__":
    create_tables()