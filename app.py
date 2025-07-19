from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
import json
import os
import logging

if not os.path.isdir('logs'):
    os.mkdir('logs')
    
logging.getLogger('werkzeug').disabled = True
logging.basicConfig(
    filename="logs/server.log",
    level=logging.DEBUG,
    datefmt='%Y/%m/%d %H:%M:%S',
    format='%(asctime)s:%(levelname)s:%(message)s'
)

app = Flask(__name__)
app.secret_key = 'hongsfirstproject'

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
        
        # plans 테이블 생성 (체크리스트 컬럼 추가)
        c.execute('''
        CREATE TABLE IF NOT EXISTS plans (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            plan TEXT,
            result TEXT,
            reflection TEXT,
            plan_date TEXT,
            checklist JSONB
        )
        ''')
        
        # 기존 테이블에 checklist 컬럼이 없다면 추가
        c.execute('''
        ALTER TABLE plans 
        ADD COLUMN IF NOT EXISTS checklist JSONB
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
            plan = request.form.get('plan', '')
            result = request.form.get('result', '')
            reflection = request.form.get('reflection', '')
            plan_date = request.form.get('date', '')
            user_id = session['user_id']
            
            # 체크리스트 데이터 처리
            checklist_json = request.form.get('checklist', '[]')
            try:
                checklist = json.loads(checklist_json) if checklist_json else []
            except json.JSONDecodeError:
                checklist = []
            
            conn = get_db_connection()
            c = conn.cursor()
            
            # 이미 있으면 UPDATE, 없으면 INSERT
            c.execute("SELECT id FROM plans WHERE user_id=%s AND plan_date=%s", (user_id, plan_date))
            existing_plan = c.fetchone()
            
            if existing_plan:
                c.execute(
                    "UPDATE plans SET plan=%s, result=%s, reflection=%s, checklist=%s WHERE user_id=%s AND plan_date=%s",
                    (plan, result, reflection, json.dumps(checklist), user_id, plan_date)
                )
                app.logger.info(f"사용자 {session['username']}의 {plan_date} 계획 업데이트")
            else:
                c.execute(
                    "INSERT INTO plans (user_id, plan, result, reflection, plan_date, checklist) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, plan, result, reflection, plan_date, json.dumps(checklist))
                )
                app.logger.info(f"사용자 {session['username']}의 {plan_date} 새 계획 저장")
            
            conn.commit()
            conn.close()
            message = "계획이 성공적으로 저장되었습니다! 🎉"
        
        return render_template('student_home.html', username=session['username'], message=message)

@app.route('/get_plan', methods=['POST'])
def get_plan():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
        
    user_id = session['user_id']
    plan_date = request.form.get('date', '')
    
    if not plan_date:
        return jsonify({'error': 'Date required'}), 400
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT plan, result, reflection, checklist FROM plans WHERE user_id=%s AND plan_date=%s", 
              (user_id, plan_date))
    row = c.fetchone()
    conn.close()
    
    if row:
        # 체크리스트 데이터 파싱
        checklist = []
        if row[3]:  # checklist 컬럼이 있고 값이 있을 때
            try:
                checklist = json.loads(row[3]) if isinstance(row[3], str) else row[3]
            except (json.JSONDecodeError, TypeError):
                checklist = []
        
        return jsonify({
            'plan': row[0] or '',
            'result': row[1] or '',
            'reflection': row[2] or '',
            'checklist': checklist
        })
    else:
        return jsonify({
            'plan': '',
            'result': '',
            'reflection': '',
            'checklist': []
        })

# 선생님이 학생 계획 보기
@app.route('/view_student/<student_name>')
def view_student(student_name):
    if 'user_id' not in session or session['role'] != 'teacher':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    c = conn.cursor()
    
    # 학생 정보 가져오기
    c.execute("SELECT id FROM users WHERE username=%s AND role='student'", (student_name,))
    student = c.fetchone()
    
    if not student:
        conn.close()
        return "학생을 찾을 수 없습니다.", 404
    
    # 학생의 모든 계획 가져오기 (최근순)
    c.execute("""
        SELECT plan_date, plan, result, reflection, checklist 
        FROM plans 
        WHERE user_id=%s 
        ORDER BY plan_date DESC 
        LIMIT 30
    """, (student[0],))
    
    plans = c.fetchall()
    conn.close()
    
    # 체크리스트 데이터 파싱
    formatted_plans = []
    for plan in plans:
        checklist = []
        if plan[4]:  # checklist 컬럼
            try:
                checklist = json.loads(plan[4]) if isinstance(plan[4], str) else plan[4]
            except (json.JSONDecodeError, TypeError):
                checklist = []
        
        formatted_plans.append({
            'date': plan[0],
            'plan': plan[1] or '',
            'result': plan[2] or '',
            'reflection': plan[3] or '',
            'checklist': checklist
        })
    
    return render_template('view_student.html', 
                         student_name=student_name, 
                         plans=formatted_plans)

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
            app.logger.info(f"사용자 {username} 로그인 성공")
            return redirect(url_for('dashboard'))
        else:
            app.logger.warning(f"로그인 실패: {username}")
            return render_template('login.html', error='아이디 또는 비밀번호가 틀렸습니다.')
    
    return render_template('login.html')

# 로그아웃
@app.route('/logout')
def logout():
    username = session.get('username', 'Unknown')
    app.logger.info(f"사용자 {username} 로그아웃")
    session.clear()
    return redirect(url_for('home'))

# 에러 핸들러
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal server error: {error}")
    return render_template('500.html'), 500

if __name__ == '__main__':
    # 앱 시작할 때 DB 초기화
    init_db()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
