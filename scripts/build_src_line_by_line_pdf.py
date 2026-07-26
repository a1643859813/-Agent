"""Create a no-prerequisite, line-by-line reading guide for src/*.py without changing source code."""
from __future__ import annotations

from html import escape
from pathlib import Path
import re
import textwrap

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Preformatted, Spacer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "src逐行讲解_JavaC基础过渡版.pdf"
FONT = "MicrosoftYaHei"
pdfmetrics.registerFont(TTFont(FONT, r"C:\Windows\Fonts\msyh.ttc"))

ORDER = ["__init__.py", "types.py", "store.py", "tools.py", "llm.py", "tasks.py", "runtime.py"]
FILE_INTRO = {
    "__init__.py": "最短的文件。它把 src 标记为一个 Python 包，让其他文件能够写 from src.runtime import ...。",
    "types.py": "先定义全项目都要用的数据形状。它类似 Java 的 DTO/POJO，或 C 里约定好的 struct。",
    "store.py": "本地数据层。负责把 session、长期记忆、待办、事件保存到 JSON 文件。",
    "tools.py": "工具层。负责登记工具、检查参数并实际执行 calculator、todo 和异步任务工具。",
    "llm.py": "模型通信层。负责调用 DeepSeek HTTP API、请求摘要、解析 function calling。",
    "tasks.py": "异步任务层。负责后台执行耗时任务、取消任务，并把完成事件交回 session。",
    "runtime.py": "最重要的 Agent 大脑。把模型、工具、记忆、上下文、队列连接成 Agent Loop。",
}

FUNCTION_NOTES = {
    "__init__": "构造函数：创建对象时自动执行，用来准备这个对象后续工作需要的状态。",
    "_save": "私有辅助方法：把内存中的 data 写回 JSON 文件。前导下划线表示‘只给类内部使用’的约定。",
    "session": "根据 user_id 和 session_id 取出一个聊天窗口的数据；没有就创建一个。",
    "save_session": "把一个 session 放回总数据并保存到硬盘。",
    "claim_session": "尝试把 session 标记为 busy；若已忙，就把新消息放入 FIFO 队列。",
    "finish_session": "把本轮请求结束的 session 改回 idle，让下一条排队消息可执行。",
    "claim_next_input": "从等待队列取出最早的一条消息，并再次把 session 标记成 busy。",
    "add_event": "把异步任务的完成/失败/取消消息加入当前 session 的事件列表。",
    "list_events": "读取事件；clear=True 时读完同时清空。",
    "remember": "向用户级长期记忆写入一条信息。",
    "recall": "从同一个用户的长期记忆中按简单匹配规则取 Top K 条。",
    "add_todo": "给某个聊天窗口添加待办。",
    "list_todos": "列出某个聊天窗口的待办。",
    "schema": "把工具自身描述转换为 DeepSeek function calling 需要的 JSON 格式。",
    "validate": "在真正执行工具之前检查参数是否完整、枚举值是否有效。",
    "register": "把一个工具放入 registry；同名工具不允许覆盖。",
    "schemas": "收集所有工具的 Schema，准备一起发给模型。",
    "execute": "按工具名找到工具，先校验参数，再调用该工具的 handler。",
    "_calculate": "用 AST 白名单计算表达式，避免直接 eval 带来的任意代码执行风险。",
    "build_default_registry": "创建并注册本项目默认工具。",
    "_request": "最底层网络请求：把 messages 和 tools 发送给 DeepSeek。",
    "chat": "普通 Agent 对话调用：请求模型并把响应解析成 LLMReply。",
    "summarize": "摘要调用：让模型把旧聊天压缩成固定 JSON 结构。",
    "normalise": "检查并补齐摘要 JSON 的四个键，保证 Runtime 使用时格式稳定。",
    "parse": "从模型回复中取出原生 tool_calls；也兼容 Markdown 里的 JSON 工具指令。",
    "submit": "创建一个异步任务并放入线程池，立刻返回 task_id。",
    "cancel": "给指定任务发出取消信号。任务需要自己检查这个信号后退出。",
    "status": "查询某个任务当前状态和结果。",
    "_owned": "校验 task_id 是否属于当前 user 和 session，防止串任务。",
    "shutdown": "关闭线程池，等待后台线程收尾。",
    "delayed_search": "可取消的模拟搜索：用短暂等待来演示长耗时网络任务。",
    "run": "Agent 的对外入口：先处理 busy 状态，再开始本次请求。",
    "drain_next": "当前请求结束后，取出并执行一条排队消息。",
    "_run_claimed": "真正的 Agent Loop：写入输入、组装上下文、调用模型、执行工具、直到得到最终回答。",
    "_context": "按照系统提示、长期记忆、摘要、最近消息的顺序拼出发送给模型的 Context。",
    "_compress": "历史太长时，优先让模型输出结构化摘要；失败时使用文本兜底摘要。",
    "_explicit_memory": "只在用户明确说‘记住……’时写入长期记忆。",
}


def explain(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "空行：只用于把不同逻辑段落隔开，不执行任何操作。"
    if stripped.startswith("#"):
        return "注释：Python 会忽略这一行。它是写给人看的说明，帮助你理解设计原因。"
    if stripped.startswith("from __future__"):
        return "启用延迟解析类型标注。初学阶段可把它当成类型提示的兼容设置，不影响业务流程。"
    if stripped.startswith("from ") or stripped.startswith("import "):
        return "导入：类似 Java 的 import。把别的模块、类或函数拿到当前文件使用。"
    if stripped.startswith("@dataclass"):
        return "装饰器：让 Python 自动生成构造函数等常见方法。效果接近 Java 中简化 POJO 的工具。"
    if stripped.startswith("class "):
        name = stripped.split()[1].split("(")[0].rstrip(":")
        return f"定义类 {name}。类可以理解为 Java 的 class：把数据和处理数据的方法组织在一起。"
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return "文档字符串：描述类或函数的用途，通常可被 IDE、help() 等工具读取。"
    if stripped.startswith("def ") or stripped.startswith("async def "):
        match = re.search(r"def\s+([a-zA-Z_]\w*)", stripped)
        name = match.group(1) if match else "这个函数"
        return FUNCTION_NOTES.get(name, f"定义函数 {name}。括号里是输入参数，箭头后的类型提示表示它预计返回什么。")
    if stripped.startswith("return "):
        return "return：结束当前函数，并把右边的值交回调用它的地方。类似 Java/C 中的 return。"
    if stripped == "return":
        return "return：直接结束当前函数，但不返回具体数据。"
    if stripped.startswith("if "):
        return "条件判断：条件为真时才执行后面缩进的代码块。冒号后的缩进在 Python 中相当于 C/Java 的花括号。"
    if stripped.startswith("elif "):
        return "否则再判断一个条件；只有前面的 if/elif 都不成立时才会检查这里。"
    if stripped == "else:":
        return "否则：前面的条件都不成立时执行这个缩进代码块。"
    if stripped.startswith("for "):
        return "循环：依次取出集合中的每个元素执行一次代码。类似 Java 的增强 for 循环。"
    if stripped.startswith("while "):
        return "循环：只要条件为真就重复执行。这里通常会检查取消信号或等待任务完成。"
    if stripped.startswith("with "):
        return "with：进入一个受管理的代码块。这里用于加锁，离开缩进块后会自动释放锁。"
    if stripped == "try:":
        return "try：尝试执行可能失败的代码；如果报错，流程会跳到后面的 except。"
    if stripped.startswith("except "):
        return "except：捕获 try 中发生的异常，避免整个程序直接终止。"
    if stripped == "finally:":
        return "finally：无论 try 成功、失败或提前 return，都会执行。适合做释放 session、保存数据等收尾工作。"
    if stripped.startswith("raise "):
        return "raise：主动抛出错误，告诉上层调用者输入不合法或当前状态不允许操作。"
    if stripped.startswith("break"):
        return "break：立刻跳出当前最近的一层循环。"
    if stripped.startswith("continue"):
        return "continue：跳过本次循环剩余部分，直接开始下一轮循环。"
    # Common project expressions: explain these before falling back to generic assignment/call rules.
    if "self.data.update(json.loads" in stripped:
        return "读取 JSON 文件里的文字，先 json.loads 转回 Python 字典，再 update 合并到内存中的 self.data。"
    if "self.path = Path(path)" in stripped:
        return "把传入的路径字符串包装成 Path 对象，后面就能方便地判断文件是否存在、读取和写入。"
    if "self.lock = RLock()" in stripped:
        return "创建可重入锁。多个线程可能同时读写 JSON 数据时，用它保证一次只有一个操作修改数据。"
    if "self.data:" in stripped and "sessions" in stripped:
        return "创建总数据字典。它有三块：sessions（短期上下文）、user_memories（长期记忆）、todos（待办）。"
    if ".setdefault(" in stripped:
        return "setdefault：如果字典里已有这个键就取旧值；没有就创建默认值再返回。很适合‘没有 session 就新建 session’。"
    if ".append(" in stripped:
        return "append：把一个元素追加到列表最后。这里用于添加消息、待办、事件或排队输入。"
    if ".pop(0)" in stripped:
        return "pop(0)：取出并删除列表的第一个元素，所以等待队列遵守先进先出（FIFO）。"
    if "json.dumps" in stripped:
        return "json.dumps：把 Python 的字典/列表转换成 JSON 文本，方便写文件或作为 tool 消息传给模型。"
    if "json.loads" in stripped:
        return "json.loads：把 JSON 文本解析回 Python 的字典或列表。"
    if "sorted(" in stripped:
        return "sorted：按给出的规则把列表排序。这里会让与用户当前问题更相关的长期记忆排在前面。"
    if "for item in" in stripped and stripped.startswith(("facts =", "source =", "result =", "[")):
        return "列表推导式：把 for 循环、条件判断和收集结果写在一行；效果相当于创建空列表再循环 append。"
    if "ast.parse" in stripped:
        return "把数学表达式字符串解析成 AST 语法树，然后只允许白名单中的加减乘除节点，避免执行任意 Python 代码。"
    if "isinstance(" in stripped:
        return "isinstance：运行时检查一个值的类型。例如先确认模型传来的参数确实是字典。"
    if "_OPS[type(" in stripped:
        return "根据 AST 节点的运算符类型，从白名单 _OPS 中取出对应的加减乘除函数后执行。"
    if "urllib.request.Request" in stripped:
        return "创建 HTTP 请求对象：包含接口地址、要发送的数据和 Authorization 等请求头。"
    if "urllib.request.urlopen" in stripped:
        return "真正向 DeepSeek 发出网络请求，并设置 60 秒超时；with 结束后连接会自动关闭。"
    if "ToolCallParser.parse" in stripped:
        return "把 DeepSeek 返回的原始 message 转换成本项目统一使用的 LLMReply 对象。"
    if "re.sub(" in stripped:
        return "用正则替换掉模型可能包上的 ```json 代码围栏，只留下纯 JSON。"
    if "re.search(" in stripped:
        return "用正则在用户输入中查找模式；这里是在找用户是否明确说了‘记住……’。"
    if "match.group(1)" in stripped:
        return "取正则第一个括号捕获到的内容，也就是‘记住’后面真正需要保存的文字；strip 会去掉首尾标点和空格。"
    if "ThreadPoolExecutor(" in stripped:
        return "创建线程池。它能让后台任务在线程中执行，而主 Agent 不必等待任务完成。"
    if "uuid4().hex" in stripped:
        return "生成随机且几乎不会重复的 task_id，用于后续查询或取消具体任务。"
    if "self.executor.submit" in stripped:
        return "把 runner 函数提交给线程池，submit 会立刻返回 Future；任务在后台开始执行。"
    if "add_done_callback" in stripped:
        return "注册回调：后台任务无论成功、失败还是取消，结束时都会自动执行 complete。"
    if "future.result()" in stripped:
        return "取后台任务的最终结果；如果任务内部报错，这一行会重新抛出异常，交给 except 处理。"
    if "cancel_event" in stripped and "is_set" in stripped:
        return "检查取消信号。协作式取消要求任务自己主动检查这个信号，然后安全退出。"
    if "self.store.claim_session" in stripped:
        return "向 Store 请求占用 session。返回 False 表示另一个请求还在处理，因此这条消息只能排队。"
    if "self._context(" in stripped:
        return "调用 _context，把系统提示、长期记忆、摘要和最近聊天记录拼成这轮发给模型的 messages。"
    if "self.client.chat" in stripped:
        return "调用 llm.py 的客户端，请 DeepSeek 决定直接回答还是返回工具调用。"
    if "self.tools.execute" in stripped:
        return "根据模型给出的工具名和参数，调用 tools.py 中真正的本地工具。"
    if "session[\"messages\"].append" in stripped:
        return "把本轮用户消息、模型工具请求、工具结果或最终回答写入当前 session 的短期上下文。"
    if "self._compress" in stripped:
        return "检查历史是否过长；达到阈值时把旧消息压缩为摘要，避免 Context 无限增长。"
    if "self.client.summarize" in stripped:
        return "调用模型生成结构化摘要，专门保留目标、结论、未完成事项和偏好。"
    if "trace.append" in stripped:
        return "往 trace 执行日志加入一条事件。录屏或调试时可以看到 Agent 实际做了什么。"
    if "self.store.remember" in stripped:
        return "调用 Store，把用户明确要求记住的信息写到 user_id 级长期记忆中。"
    if "=" in stripped and not any(op in stripped for op in ["==", ">=", "<=", "!="]):
        if stripped.startswith("self."):
            return "给当前对象保存一个属性。self 类似 Java 的 this，后续同一个对象的方法都能使用这个值。"
        if stripped.startswith(("payload", "request")):
            return "创建网络请求需要的数据：payload 是要发送的 JSON；request 是包含地址、请求体和请求头的请求对象。"
        if stripped.startswith(("session", "messages", "memories", "tasks", "events", "result", "task")):
            return "把右边计算出的数据保存到左边变量。变量名提示了它保存的是会话、消息、记忆、任务或结果。"
        return "赋值：先计算等号右边，再把结果保存到等号左边的变量中。"
    if stripped.endswith(":"):
        return "这是一个会产生缩进代码块的语句。Python 用缩进而不是花括号来表示代码属于哪个块。"
    if "(" in stripped and ")" in stripped:
        return "函数/方法调用：点号前的对象调用某个能力；括号里是传入的参数。"
    return "普通表达式：这一行会计算或访问一个值，具体作用要结合上下文的变量名一起看。"


def visual_code(line_no: int, line: str, width: int = 105) -> str:
    prefix = f"{line_no:>3}  "
    if not line:
        return prefix + "<空行>"
    chunks = textwrap.wrap(line, width=width, replace_whitespace=False, drop_whitespace=False, break_long_words=True, break_on_hyphens=False) or [""]
    return "\n".join([prefix + chunks[0], *["     > " + value for value in chunks[1:]]])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#617083"))
    canvas.drawString(15 * mm, 10 * mm, "src 逐行讲解 - Java/C 基础过渡版")
    canvas.drawRightString(195 * mm, 10 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontName=FONT, fontSize=23, leading=33, textColor=colors.HexColor("#103D67"), spaceAfter=5 * mm)
    heading = ParagraphStyle("heading", parent=styles["Heading1"], fontName=FONT, fontSize=16, leading=24, textColor=colors.HexColor("#103D67"), spaceBefore=3 * mm, spaceAfter=3 * mm)
    subheading = ParagraphStyle("subheading", parent=styles["Heading2"], fontName=FONT, fontSize=11.5, leading=18, textColor=colors.HexColor("#1C6B8B"), spaceBefore=3 * mm, spaceAfter=2 * mm)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=FONT, fontSize=9.5, leading=16, textColor=colors.HexColor("#1E293B"), spaceAfter=2 * mm)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=14)
    code = ParagraphStyle("code", parent=styles["Code"], fontName=FONT, fontSize=7.7, leading=11.5, textColor=colors.HexColor("#15283B"), backColor=colors.HexColor("#F1F6FA"), leftIndent=3 * mm, rightIndent=3 * mm, spaceBefore=1.5 * mm, spaceAfter=1.5 * mm)

    frame = Frame(15 * mm, 16 * mm, A4[0] - 30 * mm, A4[1] - 30 * mm, id="normal")
    document = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    document.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=footer)])

    story = [
        Spacer(1, 18 * mm),
        Paragraph("src 源码逐行讲解", title),
        Paragraph("适合：会一点 Java/C，但 Python 语法几乎忘了；希望每一行都能知道‘它在做什么、为什么需要它’。", body),
        Paragraph("约束：本 PDF 只读取现有 src 代码生成，不修改项目源码，不读取 .env，不调用 DeepSeek API。", small),
        Spacer(1, 5 * mm),
        Paragraph("建议阅读顺序", heading),
        Paragraph("1. __init__.py：认识 Python 包。2. types.py：认识项目里的数据对象。3. store.py：理解 Session 与长期记忆。4. tools.py：理解工具注册。5. llm.py：理解模型通信。6. tasks.py：理解异步。7. runtime.py：最后阅读 Agent Loop。", body),
        Paragraph("Python 和 Java/C 的三个关键区别", heading),
        Paragraph("(1) Python 用缩进表示代码块，不用大括号。<br/>(2) 变量通常不用提前声明类型，`x = 3` 就能使用；类型标注多是提示。<br/>(3) `self` 相当于 Java 的 `this`，表示当前对象。", body),
        Paragraph("每行的阅读格式", heading),
        Paragraph("灰色框是原始代码和行号；其后‘白话解释’紧跟这行代码。空行也会标出，用于说明为什么代码分段。", body),
        PageBreak(),
    ]

    for filename in ORDER:
        source = (ROOT / "src" / filename).read_text(encoding="utf-8")
        story.extend([
            Paragraph(filename, heading),
            Paragraph(FILE_INTRO[filename], body),
            Paragraph("逐行开始", subheading),
        ])
        for line_no, line in enumerate(source.splitlines(), 1):
            story.append(Preformatted(visual_code(line_no, line), code, maxLineLength=10000))
            story.append(Paragraph(f"<b>白话解释：</b>{escape(explain(line))}", small))
        story.append(PageBreak())

    document.build(story)
    print(OUT)


if __name__ == "__main__":
    build()
