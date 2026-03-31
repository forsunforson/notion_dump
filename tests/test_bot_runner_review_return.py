from app.jobs.bot_runner import _prefer_review_tool_output


def test_prefer_review_tool_output_monthly_overrides_llm_reply():
    out = _prefer_review_tool_output(
        "抱歉，系统内部索引错误",
        executed={"generate_monthly_review": 1},
        tool_outputs={"generate_monthly_review": "## monthly report"},
    )
    assert out == "## monthly report"


def test_prefer_review_tool_output_weekly_overrides_llm_reply():
    out = _prefer_review_tool_output(
        "随便说点别的",
        executed={"generate_weekly_review": 2},
        tool_outputs={"generate_weekly_review": "## weekly report"},
    )
    assert out == "## weekly report"


def test_prefer_review_tool_output_falls_back_to_llm_reply():
    out = _prefer_review_tool_output(
        "ok",
        executed={},
        tool_outputs={},
    )
    assert out == "ok"


def test_prefer_review_tool_output_falls_back_to_default_message():
    out = _prefer_review_tool_output(
        None,
        executed={},
        tool_outputs={},
    )
    assert "抱歉" in out
