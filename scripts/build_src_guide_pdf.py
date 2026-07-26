"""Generate a beginner-friendly PDF that contains every src/*.py file and explanations."""
from __future__ import annotations

from html import escape
from pathlib import Path
import textwrap

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Preformatted, Spacer


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "src代码逐个讲解_零基础版.pdf"
FONT = "MicrosoftYaHei"
pdfmetrics.registerFont(TTFont(FONT, r"C:\Windows\Fonts\msyh.ttc"))

EXPLANATIONS = {
    "__init__.py": {
        "role": "包标记文件。它告诉 Python：src 是一个可以被导入的代码包。",
        "read": "内容很短，只需要知道有它以后，main.py 才能写 from src.runtime import AgentRuntime。",
        "focus": "它本身不放业务逻辑，作用是组织项目目录。",
    },
    "types.py": {
        "role": "数据合同。它规定模型回复、工具调用结果、最终 Agent 结果分别长什么样。",
        "read": "先认识三个 @dataclass：ToolCall 是一次工具请求；LLMReply 是模型的一次回复；AgentResult 是 Runtime 最终交给 main.py 的结果。",
        "focus": "把它理解为三张固定格式的表格。其他文件只要遵循这些格式，就能协同工作。",
    },
    "store.py": {
        "role": "本地记忆本。它把 session 短期上下文、用户长期记忆、待办和任务事件保存进 JSON 文件。",
        "read": "重点看 session()、remember()/recall() 和 claim_session()/claim_next_input()。前者区分短期与长期记忆，后者实现 busy 队列。",
        "focus": "user_id 决定谁的长期记忆；user_id + session_id 决定哪个聊天窗口的数据。",
    },
    "tools.py": {
        "role": "工具箱和工具管理员。模型只能从这里注册过的工具中选择。",
        "read": "先看 Tool 的四项信息，再看 ToolRegistry 的 register、schemas、execute；最后看 calculator、todo 和异步任务工具如何被注册。",
        "focus": "工具 Schema 是给模型看的说明书；validate 是 Runtime 执行前的安全检查。",
    },
    "llm.py": {
        "role": "DeepSeek 通信层。它只负责把消息发给 API、拿回回复，并解析出工具调用。",
        "read": "_request 是最底层 HTTP 请求；chat 用于正常对话；summarize 用于生成结构化摘要；ToolCallParser 解析模型输出。",
        "focus": "这层没有 Agent Loop。真正决定“继续调用工具还是结束”的逻辑在 runtime.py。",
    },
    "tasks.py": {
        "role": "后台任务管理员。它让耗时工具先返回 task_id，在后台执行，完成后向所属 session 写入事件。",
        "read": "submit 创建任务并放入线程池；complete 处理完成/失败/取消；cancel 发送协作式取消信号。",
        "focus": "Python 不适合强杀运行中线程，所以任务自己定期检查 cancel_event 后退出。",
    },
    "runtime.py": {
        "role": "Agent 的核心大脑。它把模型、工具、记忆和 session 状态串成完整循环。",
        "read": "按 run → _run_claimed → _context → _compress → _explicit_memory 的顺序看。",
        "focus": "最关键循环是：组装 Context → 调模型 → 有工具就执行并把结果回传 → 没工具就返回最终答案。",
    },
}


def wrap_code(source: str, width: int = 126) -> str:
    """Wrap visual lines only; every source character is still present in the PDF."""
    result: list[str] = []
    for line_number, line in enumerate(source.splitlines(), 1):
        prefix = f"{line_number:>3}  "
        if not line:
            result.append(prefix)
            continue
        chunks = textwrap.wrap(line, width=width, replace_whitespace=False, drop_whitespace=False, break_long_words=True, break_on_hyphens=False) or [""]
        result.append(prefix + chunks[0])
        # Use ASCII continuation text so every PDF renderer can display it.
        result.extend("     > " + chunk for chunk in chunks[1:])
    return "\n".join(result)


def page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#5B677A"))
    canvas.drawString(15 * mm, 10 * mm, "最小 Agent Runtime - src 代码逐个讲解")
    canvas.drawRightString(282 * mm, 10 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontName=FONT, fontSize=24, leading=34, textColor=colors.HexColor("#123E67"), spaceAfter=8 * mm)
    heading = ParagraphStyle("heading", parent=styles["Heading1"], fontName=FONT, fontSize=17, leading=25, textColor=colors.HexColor("#123E67"), spaceBefore=4 * mm, spaceAfter=4 * mm)
    subheading = ParagraphStyle("subheading", parent=styles["Heading2"], fontName=FONT, fontSize=11.5, leading=18, textColor=colors.HexColor("#196A8D"), spaceBefore=3 * mm, spaceAfter=2 * mm)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=FONT, fontSize=9.5, leading=16, textColor=colors.HexColor("#1E293B"))
    code = ParagraphStyle("code", parent=styles["Code"], fontName=FONT, fontSize=7.0, leading=10.0, textColor=colors.HexColor("#182534"), backColor=colors.HexColor("#F4F7FA"), leftIndent=3 * mm, rightIndent=3 * mm, spaceBefore=2 * mm, spaceAfter=4 * mm)

    page_size = landscape(A4)
    frame = Frame(15 * mm, 16 * mm, page_size[0] - 30 * mm, page_size[1] - 30 * mm, id="normal")
    document = BaseDocTemplate(str(OUT), pagesize=page_size, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    document.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=page_number)])

    story = [
        Spacer(1, 14 * mm),
        Paragraph("src 代码逐个讲解 - 零基础阅读版", title),
        Paragraph("这份 PDF 包含 src 文件夹中的全部 Python 代码。每个文件前先解释用途和阅读重点，再给出带行号的完整源码。建议按 __init__.py → types.py → store.py → tools.py → llm.py → tasks.py → runtime.py 的顺序阅读。", body),
        Spacer(1, 8 * mm),
        Paragraph("阅读方法", heading),
        Paragraph("先不要逐字理解。每个文件先回答三个问题：它负责什么？它从谁那里拿数据？它把结果交给谁？看不懂的英文函数名可以先跳过，先盯住中文注释、类名和函数名。", body),
        Paragraph("核心流程", heading),
        Paragraph("main.py 把用户问题交给 runtime.py；runtime.py 从 store.py 取记忆，交给 llm.py 请求 DeepSeek；如果模型选择工具，就用 tools.py 执行；异步工具由 tasks.py 在后台完成，并把结果事件写回 store.py。", body),
        PageBreak(),
    ]

    for filename in ["__init__.py", "types.py", "store.py", "tools.py", "llm.py", "tasks.py", "runtime.py"]:
        info = EXPLANATIONS[filename]
        source = (ROOT / "src" / filename).read_text(encoding="utf-8")
        story.extend([
            Paragraph(filename, heading),
            Paragraph(f"<b>它负责什么：</b>{escape(info['role'])}", body),
            Paragraph(f"<b>建议怎么读：</b>{escape(info['read'])}", body),
            Paragraph(f"<b>本文件最重要的理解：</b>{escape(info['focus'])}", body),
            Paragraph("完整代码（带行号）", subheading),
            Preformatted(wrap_code(source), code, maxLineLength=10000),
            PageBreak(),
        ])

    document.build(story)
    print(OUT)


if __name__ == "__main__":
    build()
