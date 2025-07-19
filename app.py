from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
import json
import os
import logging
import threading
import schedule
import time
from datetime import datetime, timedelta
import requests

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
    
    # JSON으로 직렬화해서 템플릿에 전달
    plans_json = json.dumps(formatted_plans)
    
    return render_template('view_student.html', 
                         student_name=student_name, 
                         plans=plans_json)

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

# 선생님 카카오톡 알림 함수
def send_teacher_kakao_notification(message):
    """선생님에게 카카오톡 메시지 전송"""
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    
    # 발급받은 Access Token 사용
    headers = {
        "Authorization": f"Bearer {os.environ.get('TEACHER_KAKAO_TOKEN')}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # 플래너 링크 포함
    base_url = os.environ.get('RAILWAY_STATIC_URL', 'https://your-app.railway.app')
    
    template_object = {
        "object_type": "text",
        "text": message,
        "link": {
            "web_url": base_url,
            "mobile_web_url": base_url
        }
    }
    
    data = {
        "template_object": json.dumps(template_object)
    }
    
    try:
        response = requests.post(url, headers=headers, data=data)
        if response.status_code == 200:
            app.logger.info("✅ 선생님 카카오톡 알림 전송 성공")
            return True
        else:
            app.logger.error(f"❌ 카카오톡 전송 실패: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        app.logger.error(f"❌ 카카오톡 전송 오류: {e}")
        return False

# 오전 11시 체크
def check_morning_goals():
    """오전 11시 - 목표 미작성 학생들 체크"""
    today = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H시 %M분')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 목표와 체크리스트가 모두 비어있는 학생들
        cursor.execute("""
            SELECT u.username 
            FROM users u 
            WHERE u.role = 'student' 
            AND u.id NOT IN (
                SELECT DISTINCT p.user_id 
                FROM plans p 
                WHERE p.plan_date = %s 
                AND p.plan IS NOT NULL 
                AND p.plan != ''
                AND p.checklist IS NOT NULL 
                AND p.checklist != '[]'
                AND p.checklist != 'null'
            )
        """, (today,))
        
        students_without_goals = cursor.fetchall()
        conn.close()
        
        if students_without_goals:
            student_names = [student[0] for student in students_without_goals]
            
            message = f"""📋 오전 11시 목표 미작성 알림

⏰ 시간: {current_time}
📅 날짜: {datetime.now().strftime('%m월 %d일')}

❌ 목표 미작성 학생들:
{chr(10).join([f"• {name} 학생" for name in student_names])}

총 {len(student_names)}명이 아직 오늘의 목표를 작성하지 않았습니다.

👨‍🏫 확인해보세요!"""
            
            send_teacher_kakao_notification(message)
            app.logger.info(f"오전 11시 알림 완료 - 미작성: {len(student_names)}명")
        else:
            # 모든 학생이 작성했을 때
            message = f"""✅ 오전 11시 목표 작성 현황

⏰ 시간: {current_time}
📅 날짜: {datetime.now().strftime('%m월 %d일')}

🎉 모든 학생이 목표를 작성했습니다!
훌륭해요! 👏"""
            
            send_teacher_kakao_notification(message)
            app.logger.info("오전 11시 - 모든 학생 목표 작성 완료")
        
    except Exception as e:
        app.logger.error(f"오전 11시 체크 오류: {e}")

# 오후 1시 체크
def check_afternoon_goals():
    """오후 1시 - 여전히 미작성인 학생들 재체크"""
    today = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H시 %M분')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT u.username 
            FROM users u 
            WHERE u.role = 'student' 
            AND u.id NOT IN (
                SELECT DISTINCT p.user_id 
                FROM plans p 
                WHERE p.plan_date = %s 
                AND p.plan IS NOT NULL 
                AND p.plan != ''
                AND p.checklist IS NOT NULL 
                AND p.checklist != '[]'
                AND p.checklist != 'null'
            )
        """, (today,))
        
        students_still_without_goals = cursor.fetchall()
        conn.close()
        
        if students_still_without_goals:
            student_names = [student[0] for student in students_still_without_goals]
            
            message = f"""🚨 오후 1시 목표 미작성 재알림

⏰ 시간: {current_time}
📅 날짜: {datetime.now().strftime('%m월 %d일')}

⚠️ 여전히 목표 미작성 학생들:
{chr(10).join([f"• {name} 학생" for name in student_names])}

🔥 반나절이 지났는데도 {len(student_names)}명이 계획을 세우지 않았습니다.

👨‍🏫 추가 지도가 필요할 수 있습니다!"""
            
            send_teacher_kakao_notification(message)
            app.logger.info(f"오후 1시 재알림 완료 - 여전히 미작성: {len(student_names)}명")
        else:
            message = f"""✅ 오후 1시 목표 작성 현황

⏰ 시간: {current_time}
📅 날짜: {datetime.now().strftime('%m월 %d일')}

🎉 모든 학생이 목표를 작성완료!
늦었지만 모두 계획을 세웠네요! 👍"""
            
            send_teacher_kakao_notification(message)
            app.logger.info("오후 1시 - 모든 학생 목표 작성 완료")
        
    except Exception as e:
        app.logger.error(f"오후 1시 체크 오류: {e}")

# 새벽 2시 체크
def check_late_completion():
    """새벽 2시 - 전날 회고 미작성 학생들 체크"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    yesterday_display = (datetime.now() - timedelta(days=1)).strftime('%m월 %d일')
    current_time = datetime.now().strftime('%H시 %M분')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT u.username 
            FROM users u 
            JOIN plans p ON u.id = p.user_id 
            WHERE u.role = 'student' 
            AND p.plan_date = %s 
            AND p.plan IS NOT NULL 
            AND p.plan != ''
            AND (
                p.result IS NULL OR p.result = '' OR 
                p.reflection IS NULL OR p.reflection = ''
            )
        """, (yesterday,))
        
        students_incomplete_reflection = cursor.fetchall()
        conn.close()
        
        if students_incomplete_reflection:
            student_names = [student[0] for student in students_incomplete_reflection]
            
            message = f"""🌙 새벽 2시 회고 미작성 알림

⏰ 시간: {current_time}
📅 대상일: {yesterday_display}

💭 회고 미작성 학생들:
{chr(10).join([f"• {name} 학생" for name in student_names])}

📚 {len(student_names)}명이 어제 하루 마무리를 하지 않았습니다.

👨‍🏫 학습 습관 점검이 필요할 수 있습니다."""
            
            send_teacher_kakao_notification(message)
            app.logger.info(f"새벽 2시 알림 완료 - 회고 미작성: {len(student_names)}명")
        else:
            message = f"""✅ 새벽 2시 회고 작성 현황

⏰ 시간: {current_time}
📅 대상일: {yesterday_display}

🎉 모든 학생이 어제 회고를 작성완료!
좋은 학습 습관이 자리잡고 있네요! 📝"""
            
            send_teacher_kakao_notification(message)
            app.logger.info("새벽 2시 - 모든 학생 회고 작성 완료")
        
    except Exception as e:
        app.logger.error(f"새벽 2시 체크 오류: {e}")

# 스케줄러 설정
def setup_notification_scheduler():
    """알림 스케줄러 설정"""
    
    # 오전 11:00 - 목표 미작성자 체크
    schedule.every().day.at("11:00").do(check_morning_goals)
    
    # 오후 13:00 - 목표 여전히 미작성자 재체크
    schedule.every().day.at("13:00").do(check_afternoon_goals)
    
    # 새벽 02:00 - 전날 회고 미작성자 체크
    schedule.every().day.at("02:00").do(check_late_completion)
    
    app.logger.info("""✅ 선생님 카카오톡 알림 스케줄러 설정 완료:
    🕐 11:00 - 목표 미작성자 알림
    🕐 13:00 - 목표 미작성자 재알림  
    🕑 02:00 - 회고 미작성자 알림""")

def run_scheduler():
    """스케줄러 실행"""
    app.logger.info("카카오톡 알림 스케줄러 시작")
    while True:
        schedule.run_pending()
        time.sleep(60)  # 1분마다 체크

# 테스트 라우트들
@app.route('/test_kakao')
def test_kakao():
    """카카오톡 테스트"""
    if 'user_id' not in session or session['role'] != 'teacher':
        return "권한이 없습니다", 403
    
    test_message = f"""🔔 플래너 시스템 테스트

✅ 카카오톡 알림이 정상적으로 작동하고 있습니다!

시간: {datetime.now().strftime('%H시 %M분')}
날짜: {datetime.now().strftime('%Y년 %m월 %d일')}"""
    
    result = send_teacher_kakao_notification(test_message)
    return f"테스트 메시지 {'✅ 성공' if result else '❌ 실패'}"

@app.route('/test_morning')
def test_morning():
    """오전 체크 테스트"""
    if 'user_id' not in session or session['role'] != 'teacher':
        return "권한이 없습니다", 403
    
    check_morning_goals()
    return "✅ 오전 11시 체크 테스트 완료!"

@app.route('/test_afternoon')
def test_afternoon():
    """오후 체크 테스트"""
    if 'user_id' not in session or session['role'] != 'teacher':
        return "권한이 없습니다", 403
    
    check_afternoon_goals()
    return "✅ 오후 1시 체크 테스트 완료!"

@app.route('/test_late')
def test_late():
    """새벽 체크 테스트"""
    if 'user_id' not in session or session['role'] != 'teacher':
        return "권한이 없습니다", 403
    
    check_late_completion()
    return "✅ 새벽 2시 회고 체크 테스트 완료!"

if __name__ == '__main__':
    # 데이터베이스 초기화
    init_db()
    
    # 알림 스케줄러 시작
    if os.environ.get('TEACHER_KAKAO_TOKEN'):
        setup_notification_scheduler()
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        print("🚀 카카오톡 알림 시스템이 시작되었습니다!")
    else:
        print("⚠️ TEACHER_KAKAO_TOKEN이 설정되지 않았습니다.")
        print("📱 Railway 환경변수에 토큰을 설정해주세요!")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
