from datetime import date
from decimal import Decimal
from html import escape
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_family_id, session_dep
from app.config import Settings, get_settings
from app.domain.enums import TransactionStatus
from app.repositories.transactions import TransactionRepository
from app.services.budget_engine import BudgetEngine
from app.utils.money import money

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    key: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    family_id: UUID = Depends(current_family_id),
    session: AsyncSession = Depends(session_dep),
) -> HTMLResponse:
    expected = settings.api_secret_key.get_secret_value() if settings.api_secret_key else ""
    if expected and key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dashboard key")

    snapshot = await BudgetEngine(session).get_snapshot(family_id, date.today())
    transactions = await TransactionRepository(session).list_for_family(family_id, limit=10)
    confirmed = [tx for tx in transactions if tx.status == TransactionStatus.CONFIRMED]
    draft = [tx for tx in transactions if tx.status == TransactionStatus.DRAFT]
    html = render_dashboard(snapshot=snapshot, confirmed=confirmed, draft=draft)
    return HTMLResponse(html)


def render_dashboard(snapshot: object, confirmed: list[object], draft: list[object]) -> str:
    today = date.today()
    income = snapshot.total_income  # type: ignore[attr-defined]
    mandatory = snapshot.mandatory_remaining  # type: ignore[attr-defined]
    groceries_reserved = snapshot.groceries_cycle_reserved  # type: ignore[attr-defined]
    discretionary = snapshot.discretionary_spent  # type: ignore[attr-defined]
    savings = snapshot.total_savings  # type: ignore[attr-defined]
    available = snapshot.available_to_spend  # type: ignore[attr-defined]
    free_initial = money(income - mandatory - groceries_reserved - snapshot.savings_target)  # type: ignore[attr-defined]
    free_used_pct = percent(discretionary, free_initial)
    cycle_days = max(1, (snapshot.period_end - snapshot.period_start).days + 1)  # type: ignore[attr-defined]
    elapsed_days = min(cycle_days, max(0, (today - snapshot.period_start).days + 1))  # type: ignore[attr-defined]
    cycle_elapsed_pct = percent(Decimal(elapsed_days), Decimal(cycle_days))
    free_spent_pct = percent(discretionary, max(Decimal("0.01"), free_initial))
    tempo_text = spending_tempo_text(cycle_elapsed_pct, free_spent_pct)
    future_groceries = max(Decimal("0"), groceries_reserved - snapshot.groceries_cycle_spent)  # type: ignore[attr-defined]
    future_mandatory = future_payments_total(snapshot.upcoming_payments, today)  # type: ignore[attr-defined]
    period_used = mandatory + groceries_reserved + discretionary + savings
    category_cards = render_category_cards(snapshot.category_summaries)  # type: ignore[attr-defined]
    mandatory_overview = render_mandatory_overview(snapshot.upcoming_payments, today)  # type: ignore[attr-defined]
    groceries_overview = render_groceries_overview(snapshot)
    confirmed_rows = render_transaction_rows(confirmed)
    draft_rows = render_transaction_rows(draft)
    expense_donut = render_donut(
        "Куда ушли деньги",
        discretionary,
        max(Decimal("0"), available),
        "обычные траты",
        "доступно",
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Финансовый обзор</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #20242a;
      --muted: #69717d;
      --line: #d9dee6;
      --accent: #176b5d;
      --warn: #b7791f;
      --bad: #b42318;
      --blue: #2457a6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 22px 28px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0; font-size: 24px; font-weight: 700; }}
    .period {{ margin-top: 4px; color: var(--muted); }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 22px;
      display: grid;
      gap: 18px;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ margin-top: 6px; font-size: 25px; font-weight: 750; }}
    .good {{ color: var(--accent); }}
    .warn {{ color: var(--warn); }}
    .bad {{ color: var(--bad); }}
    .grid {{
      display: grid;
      grid-template-columns: 1.25fr .75fr;
      gap: 18px;
    }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    h3 {{
      margin: 14px 0 8px;
      font-size: 14px;
      color: var(--muted);
      font-weight: 700;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 22px;
      display: grid;
      gap: 14px;
    }}
    .hero-label {{ color: var(--muted); font-size: 14px; }}
    .hero-value {{ font-size: 44px; line-height: 1; font-weight: 800; color: var(--accent); }}
    .hero-note {{ color: var(--muted); max-width: 720px; }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 12px;
    }}
    .section-title .hint {{ color: var(--muted); font-size: 13px; }}
    .breakdown {{
      display: grid;
      gap: 2px;
    }}
    .breakdown-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      padding: 8px 0;
      border-top: 1px solid var(--line);
    }}
    .breakdown-row:first-child {{ border-top: 0; }}
    .breakdown-row.total {{
      margin-top: 6px;
      border-top: 2px solid var(--ink);
      font-weight: 800;
    }}
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .mini-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px;
      background: #fbfcfd;
      display: grid;
      gap: 8px;
    }}
    .mini-title {{ font-weight: 700; overflow-wrap: anywhere; }}
    .mini-line {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .bar {{
      height: 12px;
      background: #edf0f4;
      border-radius: 99px;
      overflow: hidden;
      border: 1px solid var(--line);
    }}
    .fill {{ height: 100%; background: var(--accent); width: 0; }}
    .fill.warn {{ background: var(--warn); }}
    .fill.blue {{ background: var(--blue); }}
    .metric {{ display: grid; gap: 8px; margin-bottom: 14px; }}
    .row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 9px 0;
      border-top: 1px solid var(--line);
    }}
    .row:first-child {{ border-top: 0; }}
    .name {{ min-width: 0; overflow-wrap: anywhere; }}
    .amount {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .muted {{ color: var(--muted); }}
    .two {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }}
    .donuts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .donut-card {{
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr);
      gap: 18px;
      align-items: center;
    }}
    .donut {{
      width: 150px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: conic-gradient(var(--accent) var(--pct), #e6eaf0 0);
      display: grid;
      place-items: center;
    }}
    .donut::after {{
      content: "";
      width: 92px;
      aspect-ratio: 1;
      border-radius: 50%;
      background: var(--panel);
    }}
    .legend {{ display: grid; gap: 8px; }}
    .legend-row {{
      display: grid;
      grid-template-columns: 12px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
    }}
    .swatch {{ width: 12px; height: 12px; border-radius: 3px; background: var(--accent); }}
    .swatch.rest {{ background: #e6eaf0; border: 1px solid var(--line); }}
    .payments-list {{
      display: grid;
      gap: 10px;
    }}
    .payment-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 11px 0;
      border-top: 1px solid var(--line);
      align-items: start;
    }}
    .payment-item:first-child {{ border-top: 0; padding-top: 0; }}
    .payment-title {{
      font-weight: 650;
      overflow-wrap: anywhere;
    }}
    .payment-date {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 13px;
    }}
    .payment-line {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      padding: 10px 0;
      border-top: 1px solid var(--line);
      align-items: baseline;
    }}
    .payment-line:first-child {{ border-top: 0; padding-top: 0; }}
    .payment-amount {{
      font-variant-numeric: tabular-nums;
      font-weight: 700;
      white-space: nowrap;
      text-align: right;
    }}
    @media (max-width: 900px) {{
      .kpis, .grid, .two, .donuts, .cards-grid {{ grid-template-columns: 1fr; }}
      .hero-value {{ font-size: 36px; }}
      .donut-card {{ grid-template-columns: 120px minmax(0, 1fr); }}
      .donut {{ width: 120px; }}
      .donut::after {{ width: 74px; }}
      main {{ padding: 14px; }}
      header {{ padding: 18px 16px 10px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Финансовый обзор</h1>
    <div class="period">Зарплатный цикл: {format_date(snapshot.period_start)} — {format_date(snapshot.period_end)} · До следующего дохода: {snapshot.days_until_next_income} дн.</div>
  </header>
  <main>
    <section class="hero">
      <div class="hero-label">Доступно к тратам</div>
      <div class="hero-value">{format_money(available)}</div>
      <div class="hero-note">После обязательных платежей, продуктового резерва, обычных расходов, накоплений и резерва.</div>
    </section>

    <section class="kpis">
      {kpi("Реальный остаток", snapshot.cycle_balance_after_plan)}
      {kpi("Фактический баланс", snapshot.balance)}
      {kpi("Расходы периода", snapshot.total_expenses, "warn")}
      {kpi("Обычные траты", discretionary, "warn")}
      {kpi("Лимит в день", snapshot.safe_daily_limit, "blue")}
    </section>

    <section class="grid">
      <div class="card">
        <div class="section-title"><h2>Расшифровка доступной суммы</h2><span class="hint">кликабельная детализация будет добавлена позже</span></div>
        {render_breakdown(income, mandatory, groceries_reserved, discretionary, savings, snapshot.savings_target_remaining, snapshot.reserve_gap, available)}
      </div>

      <div class="card">
        <h2>Прогноз на конец цикла</h2>
        <div class="row"><div class="name muted">Текущий фактический баланс</div><div class="amount">{format_money(snapshot.balance)}</div></div>
        <div class="row"><div class="name muted">Ещё зарезервировано на продукты</div><div class="amount">{format_money(future_groceries)}</div></div>
        <div class="row"><div class="name muted">Ещё предстоит обязательных оплат</div><div class="amount">{format_money(future_mandatory)}</div></div>
        <div class="row"><div class="name muted">Свободно после всех резервов</div><div class="amount">{format_money(available)}</div></div>
      </div>
    </section>

    <section class="two">
      <div class="card">
        <h2>Безопасный лимит в день</h2>
        <div class="value blue">{format_money(snapshot.safe_daily_limit)}</div>
        <div class="muted">{format_money(available)} / {snapshot.days_until_next_income} дн.</div>
      </div>
      <div class="card">
        <h2>Свободный бюджет</h2>
        <div class="row"><div class="name muted">Изначально свободно</div><div class="amount">{format_money(free_initial)}</div></div>
        <div class="row"><div class="name muted">Уже потрачено</div><div class="amount">{format_money(discretionary)}</div></div>
        <div class="row"><div class="name muted">Осталось</div><div class="amount">{format_money(available)}</div></div>
        {metric("Использовано свободного бюджета", discretionary, free_used_pct, "warn", suffix=f"из {format_money(free_initial)}")}
      </div>
    </section>

    <section class="donuts">
      {expense_donut}
      {render_donut("Период от зарплаты", period_used, max(Decimal("0"), available), "зарезервировано и потрачено", "доступно")}
    </section>

    <section class="two">
      <div class="card">
        <h2>Продукты</h2>
        {groceries_overview}
      </div>
      <div class="card">
        <h2>Обязательные платежи цикла</h2>
        {mandatory_overview}
      </div>
    </section>

    <section class="card">
      <h2>Расходы по категориям</h2>
      {category_cards}
    </section>

    <section class="two">
      <div class="card">
        <h2>Фактический баланс операций</h2>
        <div class="breakdown">
          <div class="breakdown-row"><span>Доходы</span><strong>{format_money(income)}</strong></div>
          <div class="breakdown-row"><span>Расходы</span><strong>−{format_money(snapshot.total_expenses)}</strong></div>
          <div class="breakdown-row"><span>Накопления</span><strong>−{format_money(snapshot.total_savings)}</strong></div>
          <div class="breakdown-row"><span>Долги</span><strong>−{format_money(snapshot.total_debt_payments)}</strong></div>
          <div class="breakdown-row total"><span>Фактический баланс</span><strong>{format_money(snapshot.balance)}</strong></div>
        </div>
      </div>
      <div class="card">
        <h2>Темп расходов</h2>
        <div class="row"><div class="name muted">Прошло зарплатного цикла</div><div class="amount">{cycle_elapsed_pct}%</div></div>
        <div class="row"><div class="name muted">Потрачено свободного бюджета</div><div class="amount">{free_spent_pct}%</div></div>
        <div class="row"><div class="name muted">Вывод</div><div class="amount">{tempo_text}</div></div>
      </div>
    </section>

    <section class="two">
      <div class="card">
        <h2>Последние подтверждённые операции</h2>
        {confirmed_rows}
      </div>
      <div class="card">
        <h2>Черновики к подтверждению</h2>
        {draft_rows}
      </div>
    </section>
  </main>
</body>
</html>"""


def kpi(label: str, value: Decimal, tone: str = "") -> str:
    return f"""
      <div class="card">
        <div class="label">{escape(label)}</div>
        <div class="value {tone}">{format_money(value)}</div>
      </div>
    """


def metric(label: str, value: Decimal, pct: int, tone: str, suffix: str = "") -> str:
    right = f"{format_money(value)} {escape(suffix)}".strip()
    return f"""
      <div class="metric">
        <div class="row"><div class="name">{escape(label)}</div><div class="amount">{right}</div></div>
        <div class="bar"><div class="fill {tone}" style="width:{pct}%"></div></div>
      </div>
    """


def render_breakdown(
    income: Decimal,
    mandatory: Decimal,
    groceries_reserved: Decimal,
    discretionary: Decimal,
    savings: Decimal,
    savings_remaining: Decimal,
    reserve_gap: Decimal,
    available: Decimal,
) -> str:
    rows = [
        ("Доходы", income, ""),
        ("Обязательные платежи", mandatory, "−"),
        ("Продукты до конца цикла", groceries_reserved, "−"),
        ("Другие расходы", discretionary, "−"),
        ("Накопления", savings, "−"),
        ("Остаток цели накоплений", savings_remaining, "−"),
        ("Недобор резерва", reserve_gap, "−"),
    ]
    body = "".join(
        f'<div class="breakdown-row"><span>{escape(label)}</span><strong>{sign}{format_money(value)}</strong></div>'
        for label, value, sign in rows
    )
    return (
        f'<div class="breakdown">{body}'
        f'<div class="breakdown-row total"><span>Доступно к тратам</span><strong>{format_money(available)}</strong></div>'
        "</div>"
    )


def render_groceries_overview(snapshot: object) -> str:
    groceries_week = snapshot.groceries_week  # type: ignore[attr-defined]
    if groceries_week is None:
        return '<div class="muted">Бюджет продуктов на неделю не настроен.</div>'
    future_plan = max(Decimal("0"), snapshot.groceries_cycle_reserved - snapshot.groceries_cycle_spent)  # type: ignore[attr-defined]
    cycle_forecast = snapshot.groceries_cycle_reserved  # type: ignore[attr-defined]
    return f"""
      <div class="row"><div class="name muted">Текущая неделя</div><div class="amount">{format_date(groceries_week.week_start)} — {format_date(groceries_week.week_end)}</div></div>
      <div class="row"><div class="name muted">Потрачено за неделю</div><div class="amount">{format_money(groceries_week.spent)}</div></div>
      <div class="row"><div class="name muted">Недельный лимит</div><div class="amount">{format_money(groceries_week.weekly_limit)}</div></div>
      <div class="row"><div class="name muted">Осталось на неделю</div><div class="amount">{format_money(groceries_week.remaining)}</div></div>
      <div class="row"><div class="name muted">Фактически потрачено в цикле</div><div class="amount">{format_money(snapshot.groceries_cycle_spent)}</div></div>
      <div class="row"><div class="name muted">Запланировано на оставшиеся недели</div><div class="amount">{format_money(future_plan)}</div></div>
      <div class="row"><div class="name muted">Прогноз за цикл</div><div class="amount">{format_money(cycle_forecast)}</div></div>
    """


def render_mandatory_overview(payments: list[object], today: date) -> str:
    if not payments:
        return '<div class="muted">Обязательные платежи не настроены.</div>'
    paid = [payment for payment in payments if payment.payment_date and payment.payment_date < today]  # type: ignore[attr-defined]
    upcoming = [payment for payment in payments if not payment.payment_date or payment.payment_date >= today]  # type: ignore[attr-defined]
    total = money(sum((payment.amount for payment in payments), Decimal("0")))  # type: ignore[attr-defined]
    paid_total = money(sum((payment.amount for payment in paid), Decimal("0")))  # type: ignore[attr-defined]
    upcoming_total = money(sum((payment.amount for payment in upcoming), Decimal("0")))  # type: ignore[attr-defined]
    return f"""
      <h3>Уже оплачено по дате</h3>
      {render_payment_group(paid)}
      <h3>Ещё предстоит оплатить</h3>
      {render_payment_group(upcoming)}
      <div class="row"><div class="name muted">Всего обязательных платежей</div><div class="amount">{format_money(total)}</div></div>
      <div class="row"><div class="name muted">Уже оплачено</div><div class="amount">{format_money(paid_total)}</div></div>
      <div class="row"><div class="name muted">Осталось оплатить</div><div class="amount">{format_money(upcoming_total)}</div></div>
    """


def render_payment_group(payments: list[object]) -> str:
    if not payments:
        return '<div class="muted">Нет платежей.</div>'
    rows = []
    for payment in payments:
        date_text = format_date(payment.payment_date) if payment.payment_date else "дата не задана"  # type: ignore[attr-defined]
        rows.append(
            f"""
            <div class="payment-line">
              <div>
                <div class="payment-title">{escape(clean_payment_name(payment.name))}</div>
                <div class="payment-date">{date_text}</div>
              </div>
              <div class="payment-amount">{format_money(payment.amount)}</div>
            </div>
            """  # type: ignore[attr-defined]
        )
    return f'<div class="payments-list">{"".join(rows)}</div>'


def render_category_cards(categories: list[object]) -> str:
    visible = [category for category in categories if category.spent > 0 or category.monthly_limit]  # type: ignore[attr-defined]
    visible.sort(key=lambda category: category.spent, reverse=True)  # type: ignore[attr-defined]
    if not visible:
        return '<div class="muted">Пока нет подтверждённых расходов по категориям.</div>'
    cards = []
    for category in visible[:12]:
        spent = category.spent  # type: ignore[attr-defined]
        limit = category.monthly_limit  # type: ignore[attr-defined]
        remaining = max(Decimal("0"), money(limit - spent)) if limit else None
        pct = percent(spent, limit) if limit else 0
        limit_text = format_money(limit) if limit else "не установлен"
        remaining_text = format_money(remaining) if remaining is not None else "—"
        cards.append(
            f"""
            <div class="mini-card">
              <div class="mini-title">{escape(category.name)}</div>
              <div class="mini-line"><span>Потрачено</span><strong>{format_money(spent)}</strong></div>
              <div class="mini-line"><span>Лимит</span><strong>{limit_text}</strong></div>
              <div class="mini-line"><span>Осталось</span><strong>{remaining_text}</strong></div>
              <div class="bar"><div class="fill {'warn' if pct >= 90 else ''}" style="width:{pct}%"></div></div>
            </div>
            """
        )
    return f'<div class="cards-grid">{"".join(cards)}</div>'


def future_payments_total(payments: list[object], today: date) -> Decimal:
    return money(
        sum(
            (
                payment.amount
                for payment in payments
                if payment.payment_date is None or payment.payment_date >= today  # type: ignore[attr-defined]
            ),
            Decimal("0"),
        )
    )


def spending_tempo_text(cycle_elapsed_pct: int, free_spent_pct: int) -> str:
    if free_spent_pct <= cycle_elapsed_pct + 10:
        return "Темп расходов в норме"
    if free_spent_pct <= cycle_elapsed_pct + 25:
        return "Близко к лимиту"
    return "Выше лимита"


def render_donut(
    title: str,
    used: Decimal,
    remaining: Decimal,
    used_label: str,
    remaining_label: str,
) -> str:
    total = money(used + remaining)
    pct = percent(used, total)
    return f"""
      <div class="card donut-card">
        <div class="donut" style="--pct:{pct}%"></div>
        <div>
          <h2>{escape(title)}</h2>
          <div class="legend">
            <div class="legend-row">
              <span class="swatch"></span>
              <span>{escape(used_label)}</span>
              <strong>{format_money(used)}</strong>
            </div>
            <div class="legend-row">
              <span class="swatch rest"></span>
              <span>{escape(remaining_label)}</span>
              <strong>{format_money(remaining)}</strong>
            </div>
          </div>
        </div>
      </div>
    """


def render_transaction_rows(transactions: list[object]) -> str:
    if not transactions:
        return '<div class="muted">Нет операций.</div>'
    rows = []
    for tx in transactions:
        title = tx.merchant or tx.description or tx.type  # type: ignore[attr-defined]
        rows.append(
            f'<div class="row"><div class="name">{escape(str(title))}<div class="muted">{format_date(tx.transaction_date)}</div></div><div class="amount">{format_money(tx.amount)}</div></div>'  # type: ignore[attr-defined]
        )
    return "\n".join(rows)


def clean_payment_name(name: str) -> str:
    parts = name.split()
    if len(parts) < 4:
        return name
    amount_part = parts[-3].replace(",", ".")
    day_part = parts[-2]
    if is_decimal_text(amount_part) and day_part.isdigit():
        return " ".join(parts[:-3]) or name
    return name


def is_decimal_text(value: str) -> bool:
    try:
        Decimal(value)
    except Exception:
        return False
    return True


def percent(value: Decimal, total: Decimal | None) -> int:
    if total is None or total <= 0:
        return 0
    return max(0, min(100, int((money(value) / money(total)) * 100)))


def format_money(value: Decimal) -> str:
    return f"{money(value):,.2f} €".replace(",", " ").replace(".", ",")


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")
