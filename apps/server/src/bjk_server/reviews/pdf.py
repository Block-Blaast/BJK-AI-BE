"""결재용 PDF (기능명세서 F-APPROVAL-04, API 명세서 REV-07).

저장한 판정 결과·스냅샷·승인 기록만으로 HTML을 만들고 WeasyPrint로 PDF를 만든다. 생성 시각 같은
바뀌는 값을 넣지 않아 같은 검토는 다시 받아도 같은 바이트가 나온다. 그래프는 matplotlib SVG.
"""

import io
import os
from dataclasses import dataclass
from datetime import date, datetime
from html import escape

from bjk_review import ReviewResult
from bjk_review import ReviewSnapshot as SnapshotValues

from bjk_server.clock import KST
from bjk_server.domain.forecast import PROJECTION_DAYS, project_stock

# PDF 본문과 그래프가 같은 글꼴을 쓴다. 운영 이미지는 fonts-noto-cjk(Noto Sans CJK KR)
FONTS = ("Noto Sans KR", "Noto Sans CJK KR", "Apple SD Gothic Neo")
FONT = ", ".join(f'"{f}"' for f in FONTS) + ", sans-serif"

VERDICT = {"ok": "적정", "revise": "수정 권고", "hold": "보류"}
FLAG = {"urgent": "긴급", "caution": "주의", "alternative": "대안"}
LEVEL = {"urgent": "긴급", "warning": "경고", "info": "정보"}
CHECK = {
    "C-01": "수량 과다",
    "C-02": "장기 재고화",
    "C-03": "중복 발주",
    "C-04": "숨은 재고",
    "C-05": "단가 이상",
    "C-06": "더 싼 공급사",
    "C-07": "수량 부족",
    "C-08": "마감 임박",
    "C-09": "외부 리스크",
}
ENTRY = {"staff_request": "직원 요청", "stock_draft": "재고 부족 초안", "missed_draft": "놓친 발주"}


@dataclass(frozen=True)
class Approval:
    approver: str
    decided_at: datetime
    action: str | None


def _won(value: int | None) -> str:
    return "-" if value is None else f"{value:,}원"


def _day(value: date | None) -> str:
    return "-" if value is None else f"{value.month}월 {value.day}일"


def stock_projection(
    s: SnapshotValues, qty: int, lead_days: int
) -> tuple[list[float], list[float]]:
    """일별 예상 재고(발주 시, 미발주 시). 시작 재고는 S + O + H_c (domain.forecast)."""
    return project_stock(s.stock + s.incoming + s.hidden_confirmed, s.m, qty, lead_days)


def projection_svg(s: SnapshotValues, qty: int, lead_days: int) -> str:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    with_order, without = stock_projection(s, qty, lead_days)
    days = list(range(PROJECTION_DAYS + 1))
    with plt.rc_context(
        {
            "svg.fonttype": "none",
            "svg.hashsalt": "bjk-review-pdf",
            "font.size": 9,
            "font.family": [*FONTS, "DejaVu Sans"],
        }
    ):
        fig, ax = plt.subplots(figsize=(6.4, 2.6))
        ax.plot(days, with_order, label=f"발주 시 (+{qty})", color="#1f6feb")
        ax.plot(days, without, label="미발주 시", color="#d1242f", linestyle="--")
        ax.axhline(0, color="#57606a", linewidth=0.8)
        ax.set_xlabel(f"{s.as_of.isoformat()}부터 일수")
        ax.set_ylabel("예상 재고")
        ax.legend(loc="upper right", frameon=False)
        fig.tight_layout()
        out = io.StringIO()
        fig.savefig(out, format="svg", metadata={"Date": None, "Creator": None})
        plt.close(fig)
    svg = out.getvalue()
    return svg[svg.index("<svg") :]


def review_html(
    *,
    part_name: str,
    entry: str,
    result: ReviewResult,
    snapshot: SnapshotValues,
    opinion: dict,
    approval: Approval,
) -> str:
    """REV-07 구성: 발주 요약, 판정·의견, 근거 수치, 재고 추이, 미발주 리스크, 외부 요인, 승인."""
    s, o, p = snapshot, result.original, result.proposal
    ordered = p if p is not None else o
    offer = s.offer(ordered.supplier_id) or s.offer(s.default_supplier_id)
    lead = offer.lt90 if offer else 0
    flags = " · ".join(FLAG[f] for f in result.flags)
    verdict = VERDICT[result.verdict] + (f" · {flags}" if flags else "")

    def line(label: str, ln) -> str:
        if ln is None:
            return ""
        return (
            f"<tr><th>{label}</th><td>{ln.qty:,}개</td><td>{escape(ln.supplier_name or '-')}</td>"
            f"<td>{_won(ln.unit_price)}</td><td>{_won(ln.total)}</td></tr>"
        )

    basis = [
        ("S 현재 재고", f"{s.stock:,}"),
        ("O 입고 예정", f"{s.incoming:,}"),
        ("H_c / H_u 숨은 재고", f"{s.hidden_confirmed:,} / {s.hidden_unconfirmed:,}"),
        ("P 다른 열린 요청", f"{s.other_requests:,}"),
        ("m 월 소모량", f"{s.m:.1f}"),
        ("F 기간 확정 필요량", f"{s.f_period:,}"),
        ("D95 / D99", f"{s.d95:,} / {s.d99:,}"),
        ("소진 예상일 / 발주 마감일", f"{_day(s.t_out)} / {_day(s.t_deadline)}"),
        ("기본 공급사 LT90", f"{lead}일"),
    ]
    checks = "".join(
        f"<tr><td>{c.code}</td><td>{CHECK[c.code]}</td><td>{LEVEL[c.level]}</td>"
        f"<td>{escape(', '.join(f'{k} {v}' for k, v in c.facts.items()))}</td></tr>"
        for c in result.checks
    )
    risk = result.risk_if_not_ordered
    equipment = escape(", ".join(risk.equipment)) or "-"
    holidays = escape(", ".join(s.holidays_in_lead)) or "없음"
    decided = approval.decided_at.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    computed = s.computed_at.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    opinion_text = escape(opinion.get("text") or "").replace("\n", "<br>")
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>발주 검토 {escape(part_name)}</title>
<style>
@page {{ size: A4; margin: 16mm; }}
body {{ font-family: {FONT}; font-size: 10pt; color: #1f2328; }}
h1 {{ font-size: 15pt; margin: 0 0 4mm; }}
h2 {{ font-size: 11pt; margin: 6mm 0 2mm; border-bottom: 1px solid #d0d7de; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #d0d7de; padding: 1.2mm 2mm; text-align: left; }}
th {{ background: #f6f8fa; font-weight: normal; }}
.verdict {{ font-size: 12pt; font-weight: bold; }}
svg {{ width: 100%; height: auto; }}
</style></head><body>
<h1>발주 검토 결재 · {escape(part_name)}</h1>
<h2>발주 요약</h2>
<table><tr><th></th><th>수량</th><th>공급사</th><th>단가</th><th>총액</th></tr>
{line("원안", o)}{line("수정안", p)}</table>
<p>입구: {ENTRY.get(entry, entry)} · 절감액 {_won(p.saving if p else 0)}</p>
<h2>판정·검토 의견</h2>
<p class="verdict">{verdict}</p>
<p>{opinion_text}</p>
<h2>근거 수치</h2>
<table>{"".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in basis)}</table>
<table style="margin-top:2mm"><tr><th>체크</th><th>이름</th><th>등급</th><th>근거</th></tr>
{checks}</table>
<h2>재고 추이 (예측)</h2>
{projection_svg(s, ordered.qty, lead)}
<h2>미발주 리스크</h2>
<p>소진 예상 {_day(risk.stockout_date)} · 멈추는 설비 {equipment} ·
예상 손실 {_won(risk.loss)}{"(추정)" if risk.is_estimate else ""}</p>
<h2>외부 요인</h2>
<p>수입 의존 {"예" if s.import_dependent else "아니오"} · 납기 위험도 r_lead {s.r_lead:g} ·
가격 위험도 r_price {s.r_price:g} · 납기 구간 연휴 {holidays}</p>
<h2>승인</h2>
<p>승인자 {escape(approval.approver)} · {decided} · 계산 기준 {computed}</p>
</body></html>"""


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    # harfbuzz-subset이 없는 환경(CI, slim 이미지)에서는 fontTools가 글꼴을 줄이며 head.modified에
    # 현재 시각을 넣어 같은 검토도 바이트가 달라진다. 재현 빌드 규약 SOURCE_DATE_EPOCH로 고정한다.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")
    return HTML(string=html).write_pdf()
