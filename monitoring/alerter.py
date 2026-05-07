"""
Alert dispatch: console (always on) + optional email via SMTP.

Email is enabled when SMTP_HOST, SMTP_USER, SMTP_PASS, and ALERT_EMAIL_TO
are all present in the environment. HOLD signals are suppressed from email
to avoid noise; only BUY and SELL generate emails.
"""

import logging
import os
import smtplib
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

_COLORS = {
    "BUY":  "\033[92m",   # green
    "SELL": "\033[91m",   # red
    "HOLD": "\033[93m",   # yellow
    "RESET": "\033[0m",
}


@dataclass
class Alert:
    ticker: str
    action: str           # BUY | SELL | HOLD
    price: float
    norm_score: float
    rsi: float
    macd: float
    sma50: float
    sma200: float
    volatility_class: str
    raw_score: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def one_line(self) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M UTC")
        return (
            f"[{ts}] {self.action:4s} {self.ticker:6s} | "
            f"${self.price:>9.2f} | score={self.norm_score:.2f} | "
            f"RSI={self.rsi:.1f} | MACD={self.macd:.3f} | "
            f"SMA50={self.sma50:.2f} SMA200={self.sma200:.2f} | "
            f"vol={self.volatility_class}"
        )

    def email_body(self) -> str:
        return (
            f"Action   : {self.action}\n"
            f"Ticker   : {self.ticker}\n"
            f"Price    : ${self.price:.2f}\n"
            f"Score    : {self.norm_score:.2f}  (raw {self.raw_score}/6)\n"
            f"RSI      : {self.rsi:.1f}\n"
            f"MACD     : {self.macd:.3f}\n"
            f"SMA50    : {self.sma50:.2f}\n"
            f"SMA200   : {self.sma200:.2f}\n"
            f"Volatility: {self.volatility_class}\n"
            f"Time     : {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}\n"
        )


class ConsoleAlerter:
    def send(self, alert: Alert):
        c = _COLORS.get(alert.action, "")
        r = _COLORS["RESET"]
        print(f"{c}[{alert.action:4s}]{r} {alert.one_line()}")


class EmailAlerter:
    def __init__(self):
        self.host    = os.getenv("SMTP_HOST", "")
        self.port    = int(os.getenv("SMTP_PORT", "587"))
        self.user    = os.getenv("SMTP_USER", "")
        self.passwd  = os.getenv("SMTP_PASS", "")
        self.to_addr = os.getenv("ALERT_EMAIL_TO", "")

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.user and self.passwd and self.to_addr)

    def send(self, alert: Alert):
        if not self.enabled or alert.action == "HOLD":
            return
        subject = f"PlanC {alert.action}: {alert.ticker} @ ${alert.price:.2f}"
        msg = MIMEText(alert.email_body())
        msg["Subject"] = subject
        msg["From"]    = self.user
        msg["To"]      = self.to_addr
        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as s:
                s.starttls()
                s.login(self.user, self.passwd)
                s.send_message(msg)
            log.info("Email sent: %s %s", alert.action, alert.ticker)
        except Exception as exc:
            log.error("Email alert failed: %s", exc)


class AlertManager:
    """Composite alerter: dispatches to all configured channels."""

    def __init__(self):
        self._channels = [ConsoleAlerter()]
        email = EmailAlerter()
        if email.enabled:
            self._channels.append(email)
            log.info("Email alerts enabled → %s", email.to_addr)

    def send(self, alert: Alert):
        for ch in self._channels:
            try:
                ch.send(alert)
            except Exception as exc:
                log.error("%s failed: %s", type(ch).__name__, exc)
