from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

pdfmetrics.registerFont(TTFont('MicrosoftYaHei', r'C:\Windows\Fonts\msyh.ttc'))
out = Path('output/pdf/Agent_Runtime_第一版说明.pdf')
out.parent.mkdir(parents=True, exist_ok=True)
styles = getSampleStyleSheet()
title = ParagraphStyle('title', parent=styles['Title'], fontName='MicrosoftYaHei', fontSize=22, leading=30, textColor=HexColor('#153B63'))
h = ParagraphStyle('h', parent=styles['Heading2'], fontName='MicrosoftYaHei', fontSize=14, leading=22, textColor=HexColor('#153B63'), spaceBefore=12)
body = ParagraphStyle('body', parent=styles['BodyText'], fontName='MicrosoftYaHei', fontSize=10.5, leading=18)
story = [Paragraph('最小可用 Agent Runtime - 第一版', title), Paragraph('Python + DeepSeek | 重点内容预览', body), Spacer(1, 8*mm)]
story += [Paragraph('目标与边界', h), Paragraph('从零实现 Agent 主循环，不使用 LangGraph、OpenHands 等 Agent 框架。第一版优先保证循环、工具、会话、记忆、上下文、异常与可测试性完整闭环；暂不实现多 Agent、复杂权限、多渠道和异步定时任务。', body)]
rows = [['组成', '第一版实现', '关键取舍'], ['Agent Loop', '输入 -> LLM -> 工具 -> LLM/回答', '最多 5 轮，避免无限调用'], ['工具', 'calculator / mock search / todo', 'Schema 注册，LLM 自主决策'], ['Session', '(user_id, session_id) 独立历史与待办', '同用户窗口不串台'], ['Memory', 'user_id 级长期偏好', '仅“记住...”写入，Top K 召回'], ['Context', '记忆 + 摘要 + 最近消息', '长历史做基础确定性压缩'], ['可观测性', '每次 LLM 与工具写 trace', '工具异常转成结果继续对话']]
t=Table(rows, colWidths=[30*mm, 70*mm, 70*mm], repeatRows=1)
t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'MicrosoftYaHei'),('FONTSIZE',(0,0),(-1,-1),9),('LEADING',(0,0),(-1,-1),14),('BACKGROUND',(0,0),(-1,0),HexColor('#DCEAF7')),('GRID',(0,0),(-1,-1),0.35,HexColor('#9FBAD0')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
story += [Spacer(1,5*mm), t, Paragraph('数据与记忆隔离', h), Paragraph('Session Context 仅保留当前聊天窗口的对话、工具调用与摘要。User Memory 按 user_id 存储稳定偏好、长期目标等可复用信息；当前用户指令始终优先。用户 A 的 session-1 写入“偏好 Java 示例”后，session-2 可以召回；用户 B 无法查询到。', body), Paragraph('测试思路', h), Paragraph('使用 FakeClient 模拟模型回复，测试不依赖 API：① 模型发起 calculator 调用并根据结果回答；② 不存在工具或参数错误会记录错误且 loop 可继续；③ 两个 session 的待办、消息隔离；④ 同用户跨 session 的长期记忆召回与跨用户隔离；⑤ 连续工具调用触发最大轮次；⑥ 多轮历史触发摘要压缩。', body), Paragraph('DeepSeek 接入', h), Paragraph('使用 OpenAI-compatible /chat/completions 与 function calling。API Key、Base URL、Model 均放入 .env；测试和本地演示可先使用 FakeClient，真实演示时替换为 DeepSeekClient。', body)]
SimpleDocTemplate(str(out), pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm).build(story)
print(out)
