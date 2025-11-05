# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
# 确保从我们创建的 attendance_logic.py 文件导入
from attendance_logic import get_courses, run_brute_force_sign_in, run_single_sign_in

# 新增导入
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import base64
from Crypto.Cipher import AES
import random
import time
import traceback # 用于打印详细错误

app = Flask(__name__)
# 重要提示：为生产环境设置一个强密钥！
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-replace-this!')

SESSION_COURSES_KEY = 'current_courses'

# --- 白名单配置 ---
WHITELIST_FILE = "whitelist.txt"
ALLOWED_USERS = set()

def load_whitelist():
    """从白名单文件加载授权用户。"""
    global ALLOWED_USERS
    try:
        if os.path.exists(WHITELIST_FILE):
            with open(WHITELIST_FILE, 'r', encoding='utf-8') as f:
                ALLOWED_USERS = {line.strip() for line in f if line.strip()}
            if not ALLOWED_USERS:
                print(f"⚠️ [WHITELIST] 白名单文件 '{WHITELIST_FILE}' 为空。将没有用户能够登录。")
            else:
                print(f"✅ [WHITELIST] 已从 '{WHITELIST_FILE}' 加载 {len(ALLOWED_USERS)} 个授权用户。")
        else:
            # 如果白名单文件不存在，则不允许任何用户登录。
            print(f"❌ [WHITELIST] 白名单文件 '{WHITELIST_FILE}' 未找到。将没有用户能够登录。")
            ALLOWED_USERS = set() # 确保为空
    except Exception as e:
        print(f"❌ [WHITELIST] 加载白名单文件 '{WHITELIST_FILE}' 时发生错误: {e}")
        ALLOWED_USERS = set() # 出错时确保为空，阻止所有登录

load_whitelist() # 应用启动时加载白名单
# --- 白名单配置结束 ---

# --- 从 attendance_login.py 移入的加密相关方法 ---
def randString_local(length):
    baseString = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
    data = ''
    for i in range(length):
        data += baseString[random.randint(0, len(baseString) - 1)]
    return data

def encryptAES_local(password, key):
    iv_str = randString_local(16)
    
    key_bytes = key.encode('utf-8')
    iv_bytes = iv_str.encode('utf-8')

    aes = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)

    data_to_encrypt = randString_local(64) + password

    text_length = len(data_to_encrypt.encode('utf-8'))
    amount_to_pad = AES.block_size - (text_length % AES.block_size)
    if amount_to_pad == 0:
        amount_to_pad = AES.block_size
    
    pad_char = chr(amount_to_pad)
    data_padded = data_to_encrypt + pad_char * amount_to_pad

    encrypted_bytes = aes.encrypt(data_padded.encode('utf-8'))
    
    text_base64_encoded = base64.b64encode(encrypted_bytes).decode('utf-8').strip()
    return text_base64_encoded
# --- 加密相关方法结束 ---

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_input = request.form.get('username', '').strip()
        plain_password_input = request.form.get('password', '').strip()

        # --- 白名单检查 ---
        # 1. 检查白名单文件是否存在 (load_whitelist 已经处理了加载逻辑，这里主要判断是否配置)
        #    如果 ALLOWED_USERS 为空，可能是文件不存在或文件为空。
        #    为了安全，如果白名单文件不存在，load_whitelist 会使 ALLOWED_USERS 为空。
        #    如果文件存在但为空，ALLOWED_USERS 也会为空。
        #    因此，统一检查 ALLOWED_USERS 是否有内容。
        
        # 首先检查物理文件是否存在，如果不存在，则提示管理员配置
        if not os.path.exists(WHITELIST_FILE):
            flash('系统白名单功能已启用但配置文件丢失，请联系管理员。登录已禁用。', 'error')
            print(f"❌ [AUTH] 用户 '{username_input}' 尝试登录失败: 白名单文件 '{WHITELIST_FILE}' 未找到。")
            return render_template('login.html')

        # 然后检查加载后的白名单是否为空
        if not ALLOWED_USERS:
            flash('系统白名单中没有授权用户，无法登录。请联系管理员。', 'error')
            print(f"❌ [AUTH] 用户 '{username_input}' 尝试登录失败: 白名单为空或加载失败。")
            return render_template('login.html')

        # 2. 检查用户是否在白名单内
        if username_input not in ALLOWED_USERS:
            flash('您的账号未在授权名单中，无法登录。', 'error')
            print(f"❌ [AUTH] 用户 '{username_input}' 尝试登录失败: 用户不在白名单中。")
            return render_template('login.html')
        # --- 白名单检查结束 ---

        if not username_input or not plain_password_input: # 对密码进行非空检查
            flash('用户名和密码均不能为空。', 'error')
            return render_template('login.html')

        req_session = requests.Session()
        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.2228.0"
        }
        login_page_url = "https://uis.nbu.edu.cn/authserver/login?service=https://attendance.nbu.edu.cn/api/getIndex"

        try:
            # 第一步：GET 请求登录页面
            response_login_page = req_session.get(login_page_url, headers=base_headers, timeout=15, verify=False)
            response_login_page.raise_for_status()
            soup = BeautifulSoup(response_login_page.text, 'lxml')
            
            login_form_div = soup.find('div', {'id': 'pwdLoginDiv'})

            if not login_form_div:
                flash('登录失败：在页面中未能找到账号登录表单区域，学校登录页面可能已更新。', 'error')
                print("❌ 错误：在页面中未能找到ID为 'pwdLoginDiv' 的账号登录表单区域。")
                return render_template('login.html')

            lt_input = login_form_div.find('input', {'name': 'lt'})
            execution_input = login_form_div.find('input', {'name': 'execution'})
            salt_input = login_form_div.find('input', {'id': 'pwdEncryptSalt'})

            if not lt_input or not execution_input or not salt_input:
                flash('登录失败：未能从登录页面提取必要参数，学校登录页面可能已更新。', 'error')
                print("❌ 错误：在账号登录表单中未能完整获取到 lt, execution 或 pwdEncryptSalt。")
                return render_template('login.html')

            lt = lt_input.get('value')
            execution = execution_input.get('value')
            password_salt = salt_input.get('value')

            # 第二步：使用从页面获取的盐加密密码
            encrypted_password = encryptAES_local(plain_password_input, password_salt)

            # 第三步：构造登录表单数据
            login_data = {
                "username": username_input,
                "password": encrypted_password,
                "lt": lt,
                "dllt": "userNamePasswordLogin",
                "execution": execution,
                "_eventId": "submit",
                "rmShown": "1"
            }

            # 第四步：POST 请求模拟登录
            post_headers = base_headers.copy()
            post_headers.update({
                "Origin": "https://uis.nbu.edu.cn",
                "Referer": login_page_url,
                "Content-Type": "application/x-www-form-urlencoded"
            })
            login_post_url = login_page_url
            response_login = req_session.post(login_post_url, headers=post_headers, data=login_data, allow_redirects=False, timeout=20, verify=False)

            # 第五步：处理重定向，提取 ticket
            if response_login.status_code == 302:
                location = response_login.headers.get('Location')
                if not location:
                    flash('登录失败：重定向响应中缺少 Location 头。', 'error')
                    print("❌ [WEB_LOGIN] 登录请求成功 (302)，但重定向响应中缺少 Location 头")
                    return render_template('login.html')
                
                print(f"✅ [WEB_LOGIN] 登录请求成功，收到重定向: {location}")
                parsed_url = urlparse(location)
                query_params = parse_qs(parsed_url.query)
                ticket = query_params.get('ticket', [None])[0]

                if not ticket:
                    flash(f'登录失败：未能从重定向URL中提取 ticket。可能是用户名或密码错误。', 'error')
                    print(f"❌ [WEB_LOGIN] 未能从重定向URL {location} 中提取 ticket 参数")
                    if "error" in location.lower() or "failure" in location.lower():
                         print(f"❌ [WEB_LOGIN] 重定向指向了一个可能的错误页面。")
                    # 检查登录页面是否有错误提示
                    soup_error_check = BeautifulSoup(response_login_page.text, 'lxml') # 重新用GET页面的内容检查，因为POST后302，内容是空的
                    error_msg_element_on_page = soup_error_check.find(id="msg", class_="errors")
                    if error_msg_element_on_page:
                        page_error_text = error_msg_element_on_page.get_text(strip=True)
                        flash(f'登录失败提示: {page_error_text}', 'error')
                        print(f"❌ [WEB_LOGIN] 登录页面提示: {page_error_text}")

                    return render_template('login.html')
                
                print(f"✅ [WEB_LOGIN] 成功提取 ticket: {ticket[:10]}...")

                # 第六步：使用 ticket 访问目标服务
                service_url_template = "https://attendance.nbu.edu.cn/api/getIndex" # 这是service参数的值
                target_service_url = f"{service_url_template}?ticket={ticket}" # 构造实际访问的URL

                print(f"ℹ️ [WEB_LOGIN] 正在使用 ticket 访问目标服务: {target_service_url}")
                # 注意：这里用的是 req_session，它已经包含了上一步重定向时可能设置的 uis.nbu.edu.cn 的cookie
                # 访问目标服务时，期望 attendance.nbu.edu.cn 设置 JSESSIONID
                response_service = req_session.get(target_service_url, headers=base_headers, allow_redirects=True, timeout=10)
                response_service.raise_for_status()
                print("✅ [WEB_LOGIN] 成功访问目标服务")

                # 第七步：提取 JSESSIONID
                jsession_id_found = None
                for cookie in req_session.cookies:
                    if "attendance.nbu.edu.cn" in cookie.domain and cookie.name.upper() == "JSESSIONID":
                        jsession_id_found = cookie.value
                        break
                
                if jsession_id_found:
                    print(f"✅ [WEB_LOGIN] 成功获取 JSESSIONID: {jsession_id_found[:10]}...")
                    session['jsessionid'] = jsession_id_found # Flask session
                    
                    # 验证 JSESSIONID 并获取课程
                    validation_result = get_courses(jsession_id_found)
                    if validation_result['success']:
                        session[SESSION_COURSES_KEY] = validation_result.get('courses', [])
                        flash('登录成功！', 'success')
                        if not validation_result.get('courses'):
                            flash('今天似乎没有课程安排。', 'info')
                        return redirect(url_for('dashboard'))
                    else:
                        flash(f"登录成功但获取课程失败: {validation_result.get('error', '未知错误')}", 'error')
                        # 即使获取课程失败，也认为登录获取JSESSIONID是成功的，允许用户进入dashboard尝试刷新
                        return redirect(url_for('dashboard'))
                else:
                    flash('登录失败：未能从目标服务获取 JSESSIONID。', 'error')
                    print("❌ [WEB_LOGIN] 未能从 attendance.nbu.edu.cn 域获取到 JSESSIONID。")
                    print("ℹ️ [WEB_LOGIN] 当前 req_session 中的 Cookies:")
                    for cookie_debug in req_session.cookies:
                        print(f"  - Name: {cookie_debug.name}, Value: {cookie_debug.value[:10]}..., Domain: {cookie_debug.domain}")
                    return render_template('login.html')

            elif response_login.status_code == 200: # 登录失败，停留在原页面
                soup_error = BeautifulSoup(response_login.text, 'lxml')
                error_msg_element = soup_error.find(id="msg", class_="errors") # 根据实际页面错误提示元素调整
                if error_msg_element:
                    error_text = error_msg_element.get_text(strip=True)
                    flash(f'登录失败: {error_text}', 'error')
                    print(f"❌ [WEB_LOGIN] 登录失败，页面提示: {error_text}")
                else:
                    flash('登录失败：用户名或密码错误，或登录服务异常。', 'error')
                    print(f"❌ [WEB_LOGIN] 登录失败，状态码: {response_login.status_code}, 无明显错误提示。")
                return render_template('login.html')
            else:
                flash(f'登录失败：服务器返回意外状态 {response_login.status_code}。', 'error')
                print(f"❌ [WEB_LOGIN] 登录失败，状态码: {response_login.status_code}")
                print(f"❌ [WEB_LOGIN] 响应内容 (前500字符): {response_login.text[:500]}")
                return render_template('login.html')

        except requests.exceptions.RequestException as e:
            flash(f'登录过程中发生网络错误: {e}', 'error')
            print(f"❌ [WEB_LOGIN] 网络错误: {e}")
            traceback.print_exc()
            return render_template('login.html')
        except Exception as e:
            flash(f'登录过程中发生未知错误: {e}', 'error')
            print(f"❌ [WEB_LOGIN] 未知错误: {e}")
            traceback.print_exc()
            return render_template('login.html')

    # --- GET 请求部分 ---
    if 'jsessionid' in session:
        # 可选：验证 session 中的 JSESSIONID 是否仍然有效
        # 为了简单起见，我们假设如果存在就有效，让后续的 get_courses 去验证
        return redirect(url_for('dashboard'))

    return render_template('login.html')

# --- dashboard, refresh_courses, signin, logout 函数保持不变 ---
# (请确保这些函数在 app.py 文件中仍然存在且内容正确)
@app.route('/dashboard')
def dashboard():
    if 'jsessionid' not in session:
        flash('请先登录。', 'error')
        return redirect(url_for('login'))

    jsessionid_cookie = session['jsessionid']
    courses_data = session.get(SESSION_COURSES_KEY)

    # 如果 session 中没有课程缓存 (例如，session 过期后重新打开，或者直接访问 dashboard)
    # 或者用户点击了刷新按钮（虽然刷新逻辑在 refresh_courses 中处理，但以防万一）
    # 则尝试重新获取课程
    if courses_data is None: # 使用 is None 检查缓存是否存在，空列表 [] 是有效缓存
        print("缓存未命中或需要刷新，正在从 API 获取课程...")
        result = get_courses(jsessionid_cookie)
        if result['success']:
            courses_data = result['courses']
            session[SESSION_COURSES_KEY] = courses_data # 更新缓存
            if not courses_data:
                 flash(result.get('message', '今天没有找到课程。'), 'info')
        else:
            flash(f"获取课程时出错: {result['error']}", 'error')
            if "无效的 JSESSIONID" in result.get('error', ''):
                 # 如果在这里发现 cookie 失效，登出用户
                 return redirect(url_for('logout'))
            courses_data = [] # 出错时显示空列表
            session.pop(SESSION_COURSES_KEY, None) # 清除可能无效的缓存

    # (此处省略了之前 dashboard 中用于处理无课程时 message 的逻辑，因为 flash 更常用)
    # 如果 courses_data 仍然是 None (例如获取失败且未被设置为空列表)，确保模板能处理
    if courses_data is None:
        courses_data = []

    return render_template('dashboard.html', courses=courses_data)


@app.route('/refresh')
def refresh_courses():
    if 'jsessionid' not in session:
        return redirect(url_for('login'))
    session.pop(SESSION_COURSES_KEY, None)
    flash('课程列表已刷新。', 'info') # 更新提示信息
    return redirect(url_for('dashboard'))


@app.route('/signin', methods=['POST'])
def signin():
    if 'jsessionid' not in session:
        flash('会话已过期。请重新登录。', 'error')
        return redirect(url_for('login'))

    jsessionid_cookie = session['jsessionid']
    # 从 session 获取课程数据，确保后续操作基于这个数据
    courses = session.get(SESSION_COURSES_KEY)

    # 检查 courses 是否存在且不为 None
    if courses is None:
        flash('课程数据丢失，请尝试刷新页面。', 'error')
        return redirect(url_for('dashboard'))

    selected_course_ui_id = request.form.get('selected_course')
    action_type = request.form.get('action_type')

    if not selected_course_ui_id:
        flash('未选择课程。', 'error')
        return redirect(url_for('dashboard'))

    # 在 session 缓存的 courses 中查找选中的课程
    selected_course = next((c for c in courses if c.get('ui_id') == selected_course_ui_id), None)

    if not selected_course:
         flash('选择的课程无效或数据已过期，请刷新。', 'error')
         return redirect(url_for('dashboard'))

    course_plan_id = selected_course.get('coursePlanId')
    attendance_id = selected_course.get('attendanceId')
    course_name = selected_course.get('courseName', '未知课程')

    if not course_plan_id or not attendance_id:
        flash(f'无法为“{course_name}”签到。签到可能尚未发起。请刷新。', 'error')
        return redirect(url_for('dashboard'))

    result = None
    print(f"收到签到请求 - 课程: {course_name}, 类型: {action_type}") # 添加日志

    try: # 包裹签到逻辑调用，捕获意外错误
        if action_type == 'brute_force':
            flash(f'开始为“{course_name}”进行自动签到。这可能需要时间...', 'info')
            print(f"开始暴力破解 - PlanID: {course_plan_id}, AttID: {attendance_id}")
            result = run_brute_force_sign_in(jsessionid_cookie, course_plan_id, attendance_id)

        elif action_type == 'manual':
            manual_code = request.form.get('manual_code', '').strip()
            # 验证签到码格式
            try:
                code_int = int(manual_code)
                if not (0 <= code_int <= 9999):
                    raise ValueError("签到码必须在 0000 到 9999 之间。")
                manual_code_formatted = f"{code_int:04d}" # 格式化为四位
            except ValueError:
                 flash('输入的签到码无效。必须是 0000 到 9999 之间的数字。', 'error')
                 return redirect(url_for('dashboard'))

            flash(f'尝试使用签到码 {manual_code_formatted} 为“{course_name}”签到...', 'info')
            print(f"开始手动签到 - PlanID: {course_plan_id}, AttID: {attendance_id}, Code: {manual_code_formatted}")
            result = run_single_sign_in(jsessionid_cookie, course_plan_id, attendance_id, manual_code_formatted)

        else:
            flash('选择了无效的操作。', 'error')
            return redirect(url_for('dashboard'))

    except Exception as e:
        # 捕获签到逻辑中的意外错误
        print(f"执行签到操作时发生意外错误: {e}")
        flash(f"执行签到操作时发生内部错误: {e}", 'error')
        return redirect(url_for('dashboard'))


    # 处理签到结果
    if result:
        print(f"签到操作完成 - 结果: {result}") # 添加日志
        if result['success']:
            flash(f"{result['message']}", 'success')
            # 成功后，可以选择性地清除课程缓存以强制下次刷新，或者保留缓存
            # session.pop(SESSION_COURSES_KEY, None)
        else:
            flash(f"{result['error']}", 'error')
            # attempts = result.get('attempts')
            # if attempts is not None:
            #      flash(f"总尝试次数: {attempts}", 'info')
    else:
        # 如果 result 为 None (理论上不应发生，除非上面逻辑有误)
        flash("签到操作未返回有效结果。", 'warning')


    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.pop('jsessionid', None)
    session.pop(SESSION_COURSES_KEY, None)
    flash('您已成功登出。', 'success')
    return redirect(url_for('login'))

# --- Main execution ---
# ( Gunicorn in Docker runs this part, no need for __main__ block usually )
