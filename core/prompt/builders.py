from __future__ import annotations


def build_system_prompt(
    *,
    task: str,
    platform: str,
    observation_mode: str,
    tool_calling: bool = False,
    action_rules: str | None = None,
    extra_system_prompt: str | None = None,
) -> str:
    normalized_observation_mode = _normalize_observation_mode(observation_mode)

    prompt_parts = [
        (
            "You will act as an agent which follow my instruction and perform "
            f"{platform} tasks as instructed. You must have good knowledge of the current platform and good internet connection."
        ),
        _system_observation_intro(normalized_observation_mode),
        "",
    ]

    if tool_calling:
        prompt_parts.extend(
            [
                "You are required to use the provided tools to perform the action grounded to the observation.",
                "",
                "REMEMBER:",
                "For every step, you should use only the provided tools and tool schemas. NEVER EVER MAKE UP NEW TOOLS OR PARAMETERS.",
                "If you need to return a final textual response, you MUST return exactly one JSON object.",
                "You MUST NOT wrap the JSON object with backticks (`) or Markdown code fences.",
                "You MUST follow and ONLY FOLLOW from the provided tools and tool schemas, otherwise your action will be considered as invalid.",
                "The success/fail tools are terminal. Use success only when the task is actually finished in the UI or the evaluator-relevant state is already created; otherwise keep taking concrete actions.",
                "If you must click something visible in the screenshot that is missing from the accessibility tree, prefer normalized coordinates like {'x': 0.42, 'y': 0.77} instead of guessed screenshot pixel coordinates.",
            ]
        )
    else:
        if not action_rules:
            raise ValueError("action_rules is required when tool_calling is False.")
        prompt_parts.extend(
            [
                "HERE is the description of the action rules you need to predict, follow the format and choose the correct action type and parameters:",
                f"ACTION_RULES = {action_rules}",
                "",
                "REMEMBER:",
                "For every step, you should only RETURN ME THE JSON object I ASKED FOR. NEVER EVER RETURN ME ANYTHING ELSE.",
                "You MUST return exactly one JSON object.",
                "You MUST NOT wrap the JSON object with backticks (`) or Markdown code fences.",
                "You MUST follow and ONLY FOLLOW from the action rules above, otherwise your action will be considered as invalid.",
            ]
        )

    if extra_system_prompt:
        prompt_parts.extend(
            [
                "",
                extra_system_prompt,
            ]
        )

    prompt_parts.extend(
        [
            "",
            f"You are asked to complete the following task: {task}",
        ]
    )

    return "\n".join(prompt_parts).strip()


def build_step_prompt(
    *,
    observation_mode: str,
    ui_context: str | None = None,
    extra_step_prompt: str | None = None,
) -> str:
    normalized_observation_mode = _normalize_observation_mode(observation_mode)

    if normalized_observation_mode == "screenshot_only":
        prompt = (
            "Given the current screenshot as below. Up to three recent screenshots from previous steps are also available in the conversation history; compare them when helpful to judge whether the UI actually changed. What's the next step that you will do to help with the task?"
        )
    elif normalized_observation_mode == "a11y_tree_only":
        prompt = (
            f"Given the info from accessibility tree as below:\n{ui_context or ''}\n"
            "What's the next step that you will do to help with the task?"
        ).strip()
    elif normalized_observation_mode == "screenshot_and_a11y_tree":
        prompt = (
            f"Given the screenshot and info from accessibility tree as below:\n{ui_context or ''}\n"
            "Recent screenshots from the previous few steps are also available in the conversation history when helpful for comparison. What's the next step that you will do to help with the task?"
        ).strip()
    else:
        raise ValueError(
            "Unsupported observation_mode. Use 'screenshot_only', 'a11y_tree_only', or 'screenshot_and_a11y_tree'."
        )

    if extra_step_prompt:
        prompt = f"{prompt}\n\n{extra_step_prompt}"

    return prompt


def _normalize_observation_mode(observation_mode: str) -> str:
    key = observation_mode.lower().strip()
    if key not in {"screenshot_only", "a11y_tree_only", "screenshot_and_a11y_tree"}:
        raise ValueError(
            "Unsupported observation_mode. Use 'screenshot_only', 'a11y_tree_only', or 'screenshot_and_a11y_tree'."
        )
    return key


def _system_observation_intro(observation_mode: str) -> str:
    if observation_mode == "screenshot_only":
        return (
            "For each step, you will get an observation of the current screen as a screenshot. "
            "A short history of recent screenshots is also retained in the conversation so you can compare them when helpful. "
            "And you will predict the action based on the image."
        )

    if observation_mode == "a11y_tree_only":
        return (
            "For each step, you will get an observation of the current UI by accessibility tree. "
            "And you will predict the action based on the accessibility tree."
        )

    if observation_mode == "screenshot_and_a11y_tree":
        return (
            "For each step, you will get an observation of the current UI by 1) a screenshot; and 2) accessibility tree. "
            "A short history of recent screenshots is also retained in the conversation so you can compare them when helpful. "
            "And you will predict the action based on the screenshot and accessibility tree."
        )

    raise ValueError(
        "Unsupported observation_mode. Use 'screenshot_only', 'a11y_tree_only', or 'screenshot_and_a11y_tree'."
    )
