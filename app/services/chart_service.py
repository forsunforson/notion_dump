import io
import math
import datetime
from typing import Any, Iterable

from pydantic import BaseModel, Field
from pydantic import field_validator, model_validator

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
import seaborn as sns
import numpy as np


class EnergyMetrics(BaseModel):
    focus: int = Field(..., ge=1, le=10, description="专注度 (1-10)")
    anxiety: int = Field(..., ge=1, le=10, description="焦虑值 (1-10)")
    physical_energy: int = Field(..., ge=1, le=10, description="身体能量 (1-10)")
    social_desire: int = Field(..., ge=1, le=10, description="社交欲望 (1-10)")
    achievement: int = Field(..., ge=1, le=10, description="成就感 (1-10)")

    model_config = {"extra": "forbid"}


class PortfolioPosition(BaseModel):
    name: str = Field(..., min_length=1)
    weight: float = Field(..., gt=0)

    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("name must not be empty")
        return s


class PortfolioMetrics(BaseModel):
    positions: list[PortfolioPosition] = Field(..., min_length=1)
    title: str | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_weights(self) -> "PortfolioMetrics":
        w = [p.weight for p in self.positions]
        s = float(sum(w))
        if s <= 0:
            raise ValueError("positions.weight sum must be > 0")
        return self


class TrendPoint(BaseModel):
    x: datetime.date = Field(..., description="日期 (YYYY-MM-DD)")
    y: float = Field(..., description="数值")

    model_config = {"extra": "forbid"}


class TrendSeries(BaseModel):
    name: str = Field(..., min_length=1)
    points: list[TrendPoint] = Field(..., min_length=2)

    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("name must not be empty")
        return s

    @model_validator(mode="after")
    def _sorted_points(self) -> "TrendSeries":
        self.points = sorted(self.points, key=lambda p: p.x)
        xs = [p.x for p in self.points]
        if len(set(xs)) != len(xs):
            raise ValueError("points.x must be unique within a series")
        return self


class TrendMetrics(BaseModel):
    series: list[TrendSeries] = Field(..., min_length=1)
    title: str | None = None
    x_label: str | None = None
    y_label: str | None = None

    model_config = {"extra": "forbid"}


class ActivityPoint(BaseModel):
    date: datetime.date = Field(..., description="日期 (YYYY-MM-DD)")
    value: int = Field(..., ge=0, description="活跃度权重 (整数)")

    model_config = {"extra": "forbid"}


class ActivityMetrics(BaseModel):
    points: list[ActivityPoint] = Field(..., min_length=1)
    title: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    week_starts_on: int = Field(0, ge=0, le=6, description="0=Monday ... 6=Sunday")

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_range(self) -> "ActivityMetrics":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be <= end_date")
        return self


class ChartService:
    def __init__(
        self,
        *,
        dark_mode: bool = True,
        font_candidates: list[str] | None = None,
        base_facecolor: str = "#0E1117",
    ):
        self.dark_mode = dark_mode
        self.font_candidates = font_candidates or [
            "PingFang SC",
            "Hiragino Sans GB",
            "Heiti SC",
            "STHeiti",
            "Songti SC",
            "Arial Unicode MS",
            "SimHei",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
        ]
        self.base_facecolor = base_facecolor

        self._init_matplotlib()

    def _pick_chinese_font(self) -> str | None:
        try:
            existing: set[str] = set()
            for f in font_manager.fontManager.ttflist:
                name = getattr(f, "name", None)
                if name:
                    existing.add(str(name))
            for c in self.font_candidates:
                if c in existing:
                    return c
        except Exception:
            return None
        return None

    def _init_matplotlib(self) -> None:
        if self.dark_mode:
            try:
                plt.style.use("dark_background")
            except Exception:
                pass

        try:
            sns.set_theme(style="darkgrid" if self.dark_mode else "whitegrid")
        except Exception:
            pass

        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = list(self.font_candidates)
        picked = self._pick_chinese_font()
        if picked:
            matplotlib.rcParams["font.sans-serif"] = [picked] + [
                f for f in self.font_candidates if f != picked
            ]
        matplotlib.rcParams["axes.unicode_minus"] = False
        matplotlib.rcParams["figure.facecolor"] = self.base_facecolor
        matplotlib.rcParams["axes.facecolor"] = self.base_facecolor
        matplotlib.rcParams["savefig.facecolor"] = self.base_facecolor
        if self.dark_mode:
            fg = "#E6EDF3"
            matplotlib.rcParams["text.color"] = fg
            matplotlib.rcParams["axes.labelcolor"] = fg
            matplotlib.rcParams["xtick.color"] = fg
            matplotlib.rcParams["ytick.color"] = fg
            matplotlib.rcParams["axes.edgecolor"] = (1, 1, 1, 0.22)
            matplotlib.rcParams["grid.color"] = (1, 1, 1, 0.14)
            matplotlib.rcParams["axes.titlecolor"] = fg

    def _fig_to_png_bytes(self, fig) -> io.BytesIO:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=200)
        buf.seek(0)
        try:
            plt.close(fig)
        except Exception:
            pass
        return buf

    def generate_radar_chart(self, data: EnergyMetrics) -> io.BytesIO:
        labels = ["专注度", "焦虑值", "身体能量", "社交欲望", "成就感"]
        values = [
            data.focus,
            data.anxiety,
            data.physical_energy,
            data.social_desire,
            data.achievement,
        ]

        n = len(labels)
        angles = [i / n * 2 * math.pi for i in range(n)]
        angles += angles[:1]
        vals = values + values[:1]

        fig = plt.figure(figsize=(6.2, 6.2), facecolor=self.base_facecolor)
        ax = fig.add_subplot(111, polar=True)
        ax.set_facecolor(self.base_facecolor)

        ax.set_theta_offset(math.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_thetagrids([a * 180 / math.pi for a in angles[:-1]], labels, fontsize=12)

        ax.set_ylim(0, 10)
        ax.set_rgrids([2, 4, 6, 8, 10], angle=0, fontsize=9, alpha=0.8)

        color = sns.color_palette("deep")[0]
        ax.plot(angles, vals, color=color, linewidth=2)
        ax.fill(angles, vals, color=color, alpha=0.25)

        ax.grid(alpha=0.25)
        ax.spines["polar"].set_alpha(0.4)

        fig.suptitle("月度情绪与能量复盘", fontsize=16, fontweight="bold", y=1.03)
        return self._fig_to_png_bytes(fig)

    def generate_portfolio_pie(self, data: PortfolioMetrics) -> io.BytesIO:
        positions = list(data.positions)
        weights = [float(p.weight) for p in positions]
        total = float(sum(weights))
        weights = [w / total for w in weights]
        labels = [p.name for p in positions]

        max_i = max(range(len(weights)), key=lambda i: weights[i])
        explode = [0.0 for _ in weights]
        explode[max_i] = 0.08

        fig, ax = plt.subplots(figsize=(7.0, 6.0), facecolor=self.base_facecolor)
        ax.set_facecolor(self.base_facecolor)
        palette = sns.color_palette("deep", n_colors=len(weights))

        wedges, texts, autotexts = ax.pie(
            weights,
            labels=labels,
            explode=explode,
            autopct="%1.1f%%",
            startangle=90,
            colors=palette,
            pctdistance=0.75,
            textprops={"fontsize": 11},
        )

        for t in texts:
            t.set_color("white" if self.dark_mode else "black")
        for t in autotexts:
            t.set_color("white" if self.dark_mode else "black")
            t.set_fontweight("bold")

        ax.axis("equal")
        ax.set_title((data.title or "资产配置占比"), fontsize=16, fontweight="bold", pad=14)
        return self._fig_to_png_bytes(fig)

    def _smooth_xy(self, x_ord: list[int], y: list[float]) -> tuple[list[int], list[float]]:
        if np is None:
            return x_ord, y
        if len(x_ord) < 3:
            return x_ord, y

        x = np.array(x_ord, dtype=float)
        yy = np.array(y, dtype=float)

        try:
            from scipy.interpolate import make_interp_spline

            x_new = np.linspace(x.min(), x.max(), num=max(80, len(x) * 10))
            spl = make_interp_spline(x, yy, k=min(3, len(x) - 1))
            y_new = spl(x_new)
            return list(map(int, np.round(x_new))), list(map(float, y_new))
        except Exception:
            x_new = np.linspace(x.min(), x.max(), num=max(80, len(x) * 10))
            y_new = np.interp(x_new, x, yy)
            return list(map(int, np.round(x_new))), list(map(float, y_new))

    def generate_trend_line(self, data: TrendMetrics) -> io.BytesIO:
        fig, ax = plt.subplots(figsize=(9.5, 5.2), facecolor=self.base_facecolor)
        ax.set_facecolor(self.base_facecolor)

        palette = sns.color_palette("deep", n_colors=len(data.series))

        for i, s in enumerate(data.series):
            xs = [p.x for p in s.points]
            ys = [float(p.y) for p in s.points]

            x_ord = [d.toordinal() for d in xs]
            x_s, y_s = self._smooth_xy(x_ord, ys)
            x_s_dates = [datetime.date.fromordinal(int(o)) for o in x_s]

            ax.plot(
                x_s_dates,
                y_s,
                linewidth=2.2,
                color=palette[i],
                alpha=0.95,
                label=s.name,
            )
            ax.scatter(xs, ys, s=28, color=palette[i], alpha=0.9, zorder=3)

        ax.grid(alpha=0.22, linewidth=0.8)
        ax.tick_params(axis="x", rotation=0)

        ax.set_title((data.title or "趋势"), fontsize=16, fontweight="bold", pad=12)
        if data.x_label:
            ax.set_xlabel(data.x_label, fontsize=12)
        if data.y_label:
            ax.set_ylabel(data.y_label, fontsize=12)

        ax.legend(frameon=False, loc="best")
        fig.autofmt_xdate()
        return self._fig_to_png_bytes(fig)

    def _align_week_start(self, d: datetime.date, week_starts_on: int) -> datetime.date:
        delta = (d.weekday() - week_starts_on) % 7
        return d - datetime.timedelta(days=delta)

    def _build_heatmap_matrix(
        self,
        points: Iterable[ActivityPoint],
        *,
        start_date: datetime.date,
        end_date: datetime.date,
        week_starts_on: int,
    ) -> tuple[list[list[int | float]], list[datetime.date]]:
        by_date: dict[datetime.date, int] = {}
        for p in points:
            by_date[p.date] = max(by_date.get(p.date, 0), int(p.value))

        start = self._align_week_start(start_date, week_starts_on)
        end = end_date
        total_days = (end - start).days + 1
        weeks = int(math.ceil(total_days / 7))
        matrix: list[list[int | float]] = [[float("nan") for _ in range(weeks)] for _ in range(7)]
        week_starts: list[datetime.date] = [start + datetime.timedelta(days=i * 7) for i in range(weeks)]

        cur = start
        for _ in range(total_days):
            col = (cur - start).days // 7
            row = (cur.weekday() - week_starts_on) % 7
            v = by_date.get(cur)
            if v is not None:
                matrix[row][col] = int(v)
            else:
                matrix[row][col] = 0
            cur += datetime.timedelta(days=1)

        return matrix, week_starts

    def generate_activity_heatmap(self, data: ActivityMetrics) -> io.BytesIO:
        dates = [p.date for p in data.points]
        min_d = min(dates)
        max_d = max(dates)
        start_d = data.start_date or min_d
        end_d = data.end_date or max_d

        matrix, week_starts = self._build_heatmap_matrix(
            data.points,
            start_date=start_d,
            end_date=end_d,
            week_starts_on=int(data.week_starts_on),
        )

        fig, ax = plt.subplots(figsize=(10.5, 3.6), facecolor=self.base_facecolor)
        ax.set_facecolor(self.base_facecolor)

        cmap = sns.color_palette("rocket", as_cmap=True)
        sns.heatmap(
            matrix,
            ax=ax,
            cmap=cmap,
            cbar=True,
            linewidths=0.4,
            linecolor=(1, 1, 1, 0.06),
            square=True,
        )

        day_labels = ["一", "二", "三", "四", "五", "六", "日"]
        ax.set_yticks([i + 0.5 for i in range(7)])
        ax.set_yticklabels(day_labels, rotation=0, fontsize=10)

        xt = []
        xl = []
        for i, ws in enumerate(week_starts):
            if i == 0 or ws.day <= 7:
                xt.append(i + 0.5)
                xl.append(f"{ws.month:02d}/{ws.day:02d}")
        ax.set_xticks(xt)
        ax.set_xticklabels(xl, rotation=0, fontsize=9)

        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.set_title((data.title or "习惯追踪热力图"), fontsize=16, fontweight="bold", pad=10)
        return self._fig_to_png_bytes(fig)
