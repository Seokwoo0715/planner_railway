from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2  # sqlite3 대신 psycopg2
import os
import logging

if not os.path.isdir('logs'):
    os.mkdir('logs')
    
logging.getLogger('werkzeug').disabled = True
logging.basicConfig(
    filename="logs/server.log",  # 로그 파일 경로
    level=logging.DEBUG,  # 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    datefmt='%Y/%m/%d %H:%M:%S',  # 날짜 포맷
    format='%(asctime)s:%(levelname)s:%(message)s'  # 로그 포맷
)

app = Flask(__name__)
app.secret_key = 'hongsfirstproject'  # 세션을 위해 필요

# PostgreSQL 연결 함수
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    return psycopg2.connect(database_url)

# 데이터베이스 초기화 함수
def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # users 테이블 생성
        c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
        ''')
        
        # plans 테이블 생성
        c.execute('''
        CREATE TABLE IF NOT EXISTS plans (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            plan TEXT,
            result TEXT,
            reflection TEXT,
            plan_date TEXT
        )
        ''')
        
        # 기존 사용자가 있는지 확인
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        
        # 사용자가 없으면 초기 데이터 삽입
        if user_count == 0:
            # 선생님 계정
            c.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", 
                     ("Hong", "hong081430", "teacher"))
            
            # 학생 계정들
            students = [
                ("남", "kichan", "student"),
                ("김", "taejun", "student"),
                ("윤", "hyeokjun", "student"),
                ("이", "janghun", "student"),
                ("신", "seoyeon", "student")
            ]
            
            for student in students:
                c.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", student)
        
        conn.commit()
        conn.close()
        print("데이터베이스 초기화 완료!")
        
    except Exception as e:
        print(f"데이터베이스 초기화 오류: {e}")

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # 선생님 대시보드
    if session['role'] == 'teacher':
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE role='student'")
        students = c.fetchall()
        conn.close()
        return render_template('teacher_home.html', students=students)
    
    # 학생 대시보드
    else:
        app.logger.info(f"학생({session['username']})이 대시보드에 접속")
        message = None
        
        if request.method == 'POST':
            plan = request.form['plan']
            result = request.form['result']
            reflection = request.form['reflection']
            plan_date = request.form['date']
            user_id = session['user_id']
            
            conn = get_db_connection()
            c = conn.cursor()
            
            # 이미 있으면 UPDATE, 없으면 INSERT
            c.execute("SELECT id FROM plans WHERE user_id=%s AND plan_date=%s", (user_id, plan_date))
            if c.fetchone():
                c.execute(
                    "UPDATE plans SET plan=%s, result=%s, reflection=%s WHERE user_id=%s AND plan_date=%s",
                    (plan, result, reflection, user_id, plan_date)
                )
            else:
                c.execute(
                    "INSERT INTO plans (user_id, plan, result, reflection, plan_date) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, plan, result, reflection, plan_date)
                )
            
            conn.commit()
            conn.close()
            message = "계획이 저장되었습니다!"
        
        return render_template('student_home.html', username=session['username'], message=message)

@app.route('/get_plan', methods=['POST'])
def get_plan():
    user_id = session['user_id']
    plan_date = request.form['date']
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT plan, result, reflection FROM plans WHERE user_id=%s AND plan_date=%s", (user_id, plan_date))
    row = c.fetchone()
    conn.close()
    
    if row:
        return jsonify({'plan': row[0], 'result': row[1], 'reflection': row[2]})
    else:
        return jsonify({'plan': '', 'result': '', 'reflection': ''})

# 로그인 페이지
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=%s AND password=%s", (username, password))
        user = c.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='아이디 또는 비밀번호가 틀렸습니다.')
    
    return render_template('login.html')

# 로그아웃
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    # 앱 시작할 때 DB 초기화
    init_db()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)