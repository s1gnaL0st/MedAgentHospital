"""LLM-driven coordination and conversational care agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from medagent_hospital.llm.base import LLMBackend, RuleBackend, build_llm_backend

CARE_ROLES = ("guide", "nurse", "doctor", "imaging", "chief")
IMAGING_TERMS = ("影像", "CT", "X线", "X光", "核磁", "MRI", "超声", "B超", "造影", "片子")
ESCALATION_TERMS = ("会诊", "主任", "不确定", "再看看", "没把握")


@dataclass(frozen=True)
class RoutingDecision:
    target: str
    reason: str
    confidence: float = 0.0


class PatientCoordinator:
    """Coordinate open-ended patient care without making clinical decisions."""

    def __init__(self, llm: LLMBackend | None = None) -> None:
        self.llm = llm or build_llm_backend()

    def decide(self, *, stage: str, content: str, has_candidates: bool, context: dict[str, Any] | None = None) -> RoutingDecision:
        fallback = self._fallback_route(stage, content, has_candidates)
        parsed = self._call_json(self._routing_prompt(stage, content, context or {}), max_tokens=220)
        target = str((parsed or {}).get("target", "")).strip().lower()
        if target not in CARE_ROLES:
            return fallback
        try:
            confidence = float((parsed or {}).get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return RoutingDecision(target, str((parsed or {}).get("reason") or fallback.reason), confidence)

    def respond(self, role: str, *, context: dict[str, Any], patient_message: str) -> dict[str, Any]:
        parsed = self._call_json(self._agent_prompt(role, context, patient_message), max_tokens=900)
        if isinstance(parsed, dict) and str(parsed.get("content", "")).strip():
            return self._normalize(parsed, role)
        return self._fallback_response(role, context, patient_message)

    def _call_json(self, prompt: str, *, max_tokens: int) -> dict[str, Any] | None:
        try:
            text = self.llm.chat([{"role": "system", "content": prompt}], temperature=0.2, max_tokens=max_tokens)
        except Exception:
            return None
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _routing_prompt(stage: str, content: str, context: dict[str, Any]) -> str:
        return (
            "你是医院诊疗协调 Agent，只负责判断下一位工作人员，不做诊断、不编造医学结论。\n"
            "可选角色只有 guide（导医）、nurse（护士采集）、doctor（当前专科医生）、"
            "imaging（影像分析）、chief（主任会诊）。专科名称不受任何预设列表限制。\n"
            f"当前阶段：{stage}\n当前患者消息：{content}\n会话状态：{json.dumps(context, ensure_ascii=False)}\n"
            "影像资料优先交给 imaging；明确要求会诊或存在无法解释的不确定性时交给 chief；"
            "其余保持当前角色。只输出 JSON："
            '{"target":"guide|nurse|doctor|imaging|chief", "reason":"路由原因", "confidence":0.0}'
        )

    @staticmethod
    def _agent_prompt(role: str, context: dict[str, Any], patient_message: str) -> str:
        duties = {
            "guide": "接待患者、澄清主诉、判断就诊紧急程度并提出合适的专科方向；不下诊断、不直接开药。",
            "nurse": "采集现病史、生命危险信号、过敏史和用药史；发现危险信号要建议立即人工处置。",
            "doctor": "在已有信息基础上追问必要问题，提出鉴别诊断、检查和治疗参考；不确定时请求主任会诊。",
            "imaging": "解读患者上传或描述的影像资料，形成影像所见和限制说明；不独立做临床诊断。",
            "chief": "审阅交接摘要、会话和各 Agent 意见，指出不确定性并给出需要医生确认的会诊意见。",
        }
        return (
            f"你是医院中的{role} Agent。职责：{duties[role]}\n"
            "这是一个真实感的患者接诊流程模拟。请自然地和患者对话，避免固定模板，但必须保持专业、简洁、可追溯。"
            "所有结论都是辅助意见，不能声称已经完成真实诊断。\n"
            f"当前结构化状态：{json.dumps(context, ensure_ascii=False)}\n患者刚刚说：{patient_message}\n"
            "只输出 JSON："
            '{"content":"给患者看的回复", "action":"continue|handoff|request_exam|escalate|complete", '
            '"handoff_to":"guide|nurse|doctor|imaging|chief|", "department":"可为空的专科名称", '
            '"question":"下一步要问的问题，可为空", "diagnosis":"辅助判断，可为空", "confidence":0.0, '
            '"candidates":[], "exams":[], "medications":[], "reasoning":"简短依据"}'
        )

    @staticmethod
    def _normalize(value: dict[str, Any], role: str) -> dict[str, Any]:
        value = dict(value)
        value["agent"] = role
        value["content"] = str(value.get("content", "")).strip()
        value["action"] = str(value.get("action", "continue")).strip().lower()
        target = str(value.get("handoff_to", "")).strip().lower()
        value["handoff_to"] = target if target in CARE_ROLES else ""
        value["department"] = str(value.get("department", "")).strip()
        value["question"] = str(value.get("question", "")).strip()
        value["diagnosis"] = str(value.get("diagnosis", "")).strip()
        value["exams"] = _string_list(value.get("exams"))
        value["medications"] = _string_list(value.get("medications"))
        value["candidates"] = value.get("candidates") if isinstance(value.get("candidates"), list) else []
        return value

    def _fallback_route(self, stage: str, content: str, has_candidates: bool) -> RoutingDecision:
        if stage in {"triage", "guide"}:
            return RoutingDecision("guide", "导医继续澄清主诉")
        if any(term in content for term in IMAGING_TERMS) and not any(term in content for term in ("没有", "没做", "未做", "无")):
            return RoutingDecision("imaging", "患者提供了影像相关信息")
        if has_candidates and any(term in content for term in ESCALATION_TERMS):
            return RoutingDecision("chief", "患者表达了会诊或不确定需求")
        return RoutingDecision(stage if stage in CARE_ROLES else "doctor", "由当前接诊 Agent 继续处理")

    def _fallback_response(self, role: str, context: dict[str, Any], message: str) -> dict[str, Any]:
        if isinstance(self.llm, RuleBackend):
            normalized_message = message.strip()
            prompts = {
                "guide": "我先了解您的情况。请描述最困扰您的症状、什么时候开始，以及目前是否正在加重？",
                "nurse": "我来补充采集病史：目前有没有呼吸困难、意识异常、持续剧烈疼痛或其他突然加重的情况？",
                "doctor": "我会结合目前信息继续了解情况。请告诉我症状的起始时间、变化趋势，以及已经做过的检查。",
                "imaging": "我会记录并整理您提供的影像描述。仅凭文字或单张图片不能替代正式影像科报告，请由主诊医生结合原始资料判断。",
                "chief": "我已收到会诊请求。请先由主诊医生补齐必要资料，随后我会审阅完整记录并提出复核意见。",
            }
            if role == "guide" and context.get("department") and any(word in normalized_message for word in ("确认", "同意", "可以", "好")):
                return self._normalize({"content": "我已记录您的选择，现在为您转接合适的医生继续接诊。", "action": "handoff", "handoff_to": "doctor", "reasoning": "患者确认继续就诊"}, role)
            if role == "guide" and normalized_message and "刚进入医院" not in normalized_message:
                return self._normalize({"content": "我已记录您的主诉。建议先由综合评估门诊接诊，医生会根据后续信息决定是否转入更合适的专科。这样安排可以吗？", "action": "continue", "department": "综合评估门诊", "question": "是否同意先由综合评估门诊接诊？"}, role)
            if role == "doctor" and any(word in normalized_message for word in ("会诊", "主任", "不确定")):
                return self._normalize({"content": "目前信息仍不足以稳妥判断，我请求主任医师参与复核。", "action": "escalate", "handoff_to": "chief", "reasoning": "当前信息存在不确定性"}, role)
            if role == "doctor" and any(word in normalized_message for word in ("确认", "确定")):
                return self._normalize({"content": "我已整理当前接诊记录，请确认是否结束本次辅助问诊并保存记录。", "action": "complete", "diagnosis": "待医生确认的辅助判断", "exams": ["必要的相关检查"]}, role)
            if role == "doctor":
                return self._normalize({"content": "我已接收导医交接。请补充症状的起始时间、变化趋势，以及已经做过的检查。", "action": "continue", "candidates": [{"disease_name": "待进一步评估"}], "question": "症状从什么时候开始？"}, role)
            if role == "imaging":
                return self._normalize({"content": "我会记录并整理您提供的影像描述。仅凭文字或单张图片不能替代正式影像科报告，请由主诊医生结合原始资料判断。", "action": "handoff", "handoff_to": "doctor", "reasoning": "影像信息已反馈给主诊医生"}, role)
            if role == "chief" and any(word in normalized_message for word in ("确认", "确定")):
                return self._normalize({"content": "会诊意见已确认，接诊记录可以保存。", "action": "complete", "diagnosis": "待医生确认的辅助判断"}, role)
            return self._normalize({"content": prompts[role], "action": "continue"}, role)
        return self._normalize({"content": "当前模型暂时没有返回可解析的接诊结果，请稍后重试。", "action": "continue"}, role)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return []
