from PIL import Image, ImageFilter
import pytesseract

# -----------------------------------------------------------------------------
# 重要：如果 Tesseract OCR 没有在你的系统 PATH 环境变量中，
# 你需要在这里指定它的安装路径。
# 例如，在 Windows 上可能是:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# 在 Linux 或 macOS 上，如果通过包管理器安装，通常会自动添加到 PATH。
# 如果不确定，可以先尝试不设置，如果报错再取消下面这行的注释并修改路径。
# -----------------------------------------------------------------------------


def preprocess_image(image_path):
    """
    对验证码图片进行预处理。
    :param image_path: 验证码图片的路径
    :return: 处理后的 PIL Image 对象
    """
    try:
        img = Image.open(image_path)
        # 1. 转换为灰度图像
        img = img.convert('L')

        # 2. (可选) 应用中值滤波器去除噪点和一些细干扰线
        # size 参数可以调整，常见的有 3 或 5。值越大，模糊/平滑效果越强。
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # 3. (可选) 尝试形态学操作来处理粘连或断裂
        # 开运算：先腐蚀后膨胀，有助于去除小的噪点和断开细微的粘连
        # img = img.filter(ImageFilter.MinFilter(3)) # 类似腐蚀
        # img = img.filter(ImageFilter.MaxFilter(3)) # 类似膨胀

        # 闭运算：先膨胀后腐蚀，有助于填充字符内的小洞，连接断开的部分
        # img = img.filter(ImageFilter.MaxFilter(3)) # 类似膨胀
        # img = img.filter(ImageFilter.MinFilter(3)) # 类似腐蚀

        # 4. 二值化：将图像转换为黑白图像
        # 阈值需要根据实际验证码进行仔细调整。
        # 对于背景复杂或光照不均的验证码，固定阈值可能效果不佳。
        # 可以尝试不同的阈值，例如 120, 140, 160, 180 等。
        threshold = 150 # 初始建议值，请根据实际情况调整
        img = img.point(lambda x: 0 if x < threshold else 255, '1')


        # (可选) 保存预处理后的图片，方便调试和观察效果
        img.save("processed_captcha.png")
        return img
    except FileNotFoundError:
        print(f"错误：找不到图片文件 {image_path}")
        return None
    except Exception as e:
        print(f"图像预处理失败: {e}")
        return None

def recognize_text_from_image(image_object, lang='eng'):
    """
    使用 Tesseract OCR 从处理后的图像对象中识别文字。
    :param image_object: PIL Image 对象
    :param lang: 识别语言，默认为 'eng' (英文)。中文可以是 'chi_sim'。
    :return: 识别出的文本字符串（连续无空格），或在出错时返回 None
    """
    if image_object is None:
        return None
    try:
        # lang 参数指定识别语言，例如 'eng' 为英语，'chi_sim' 为简体中文
        # 需要确保已安装相应的 Tesseract 语言包
        custom_config = r'--oem 3 --psm 6' # Tesseract 配置参数，可根据需要调整
        text = pytesseract.image_to_string(image_object, lang=lang, config=custom_config)
        
        # 修改点：移除所有空白字符，确保字符串连续
        processed_text = "".join(text.split())
        return processed_text
    except pytesseract.TesseractNotFoundError:
        print("错误：Tesseract OCR 未找到。请确保它已正确安装并已配置路径（如果需要）。")
        print("提示：您可能需要在代码顶部取消注释并设置 'pytesseract.pytesseract.tesseract_cmd' 的值。")
        return None
    except Exception as e:
        print(f"OCR 识别过程中发生错误: {e}")
        return None
