"""事实提取与比对（课程 rules/fact.py 移植，编号格式适配 18081 实测口径）。

编号格式（SPEC 12.2）：订单 [ABC]\\d{11}、退款单 R…、运单 JD/SF/YT/EMS…、商品 SKU\\d+。
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.harness.snapshot import ToolCallSnapshot


class FactCategory(StrEnum):
    IDENTIFIER = "IDENTIFIER"
    NUMBER = "NUMBER"
    STATUS = "STATUS"


STATUS_CODE_MAP = {
    "待发货": "pending_shipment",
    "已发货": "shipped",
    "已完成": "completed",
    "已取消": "cancelled",
    "运输中": "in_transit",
    "已签收": "delivered",
    "派送中": "out_for_delivery",
    "待揽收": "waiting_pickup",
    "已提交": "submitted",
    "处理中": "processing",
}


@dataclass(frozen=True)
class BusinessFact:
    category: FactCategory
    value: str


class FactExtractor:
    """从回复中提取需要工具证据支持的业务事实。"""

    # 订单号 A20260408002 / 退款单 R202604070001 / 运单 JD000123456789 / 商品 SKU10002
    resource_id_pattern = re.compile(
        r"\b(?:[ABC]\d{11}|R[0-9A-Z]{12,20}|(?:JD|SF|YT|EMS)\d{6,}|SKU\d+)\b"
    )
    # 带标签的数字：金额/价格/运费/退款 …149
    labeled_number_pattern = re.compile(
        r"(?:金额|价格|运费|退款|总价)"
        r"(?:为|是|有|剩余|还剩|：|:)?\s*"
        r"[¥￥]?\s*(\d+(?:\.\d+)?)"
    )
    # 带货币符号或单位的数字：¥149 / 149元 / 3件
    unit_number_pattern = re.compile(
        r"(?:[¥￥]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:元|件|个|台|套))"
    )
    status_labels = tuple(STATUS_CODE_MAP)

    @classmethod
    def extract(cls, reply_content: str) -> tuple[BusinessFact, ...]:
        facts: dict[BusinessFact, None] = {}
        for resource_id in cls.resource_id_pattern.findall(reply_content):
            facts[BusinessFact(FactCategory.IDENTIFIER, resource_id.upper())] = None
        for number in cls.labeled_number_pattern.findall(reply_content):
            facts[BusinessFact(FactCategory.NUMBER, number)] = None
        for first, second in cls.unit_number_pattern.findall(reply_content):
            facts[BusinessFact(FactCategory.NUMBER, first or second)] = None
        for status_label in cls.status_labels:
            if status_label in reply_content:
                facts[BusinessFact(FactCategory.STATUS, status_label)] = None
        return tuple(facts)


class FactChecker:
    """比对回复事实与本 Run 成功工具调用的证据（arguments + result 递归标量）。"""

    number_pattern = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

    def get_unsupported_facts(
        self,
        reply_content: str,
        successful_tool_calls: tuple[ToolCallSnapshot, ...],
    ) -> tuple[BusinessFact, ...]:
        facts = FactExtractor.extract(reply_content)
        if not facts:
            return ()

        source_decimals: set[Decimal] = set()
        normalized_sources: set[str] = set()
        for tool_call in successful_tool_calls:
            if not tool_call.success:
                continue  # 防御：失败调用永不构成证据
            for source in (tool_call.arguments, tool_call.result):
                for scalar in self._iter_scalars(source):
                    normalized_sources.add(self._normalize_text(scalar))
                    decimal_value = self._to_decimal(scalar)
                    if decimal_value is not None:
                        source_decimals.add(decimal_value)

        return tuple(
            fact
            for fact in facts
            if not self._is_supported(fact, source_decimals, normalized_sources)
        )

    @classmethod
    def _is_supported(
        cls,
        fact: BusinessFact,
        source_decimals: set[Decimal],
        normalized_sources: set[str],
    ) -> bool:
        if fact.category == FactCategory.NUMBER:
            return Decimal(fact.value) in source_decimals

        normalized_value = cls._normalize_text(fact.value)
        if fact.category == FactCategory.STATUS:
            # 状态同时匹配中文标签与服务端编码；证据包含即视为有背书
            if normalized_value in normalized_sources:
                return True
            code = STATUS_CODE_MAP.get(fact.value)
            return code is not None and code in normalized_sources

        return normalized_value in normalized_sources

    @classmethod
    def _to_decimal(cls, value: object) -> Decimal | None:
        text = str(value).strip()
        if cls.number_pattern.fullmatch(text) is None:
            return None
        return Decimal(text)

    @staticmethod
    def _normalize_text(value: object) -> str:
        return (
            unicodedata.normalize("NFKC", str(value))
            .strip()
            .casefold()
            .replace("-", "_")
        )

    @classmethod
    def _iter_scalars(cls, value: object) -> Iterable[object]:
        if isinstance(value, dict):
            for nested in value.values():
                yield from cls._iter_scalars(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from cls._iter_scalars(nested)
        else:
            yield value
