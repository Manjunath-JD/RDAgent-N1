import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit import session_state as state

from rdagent.log.mle_summary import extract_mle_json
from rdagent.utils import remove_ansi_codes


def load_stdout():
    # FIXME: TODO: 使用配置项来指定stdout文件名
    stdout_path = state.log_folder / f"{state.log_path}.stdout"
    if stdout_path.exists():
        stdout = stdout_path.read_text()
    else:
        stdout = f"Please Set: {stdout_path}"
    return stdout


# UI windows
def task_win(data):
    with st.container(border=True):
        st.markdown(f"**:violet[{data.name}]**")
        st.markdown(data.description)
        if hasattr(data, "architecture"):  # model task
            st.markdown(
                f"""
    | Model_type | Architecture | hyperparameters |
    |------------|--------------|-----------------|
    | {data.model_type} | {data.architecture} | {data.hyperparameters} |
    """
            )


def workspace_win(data, instance_id=None):
    show_files = {k: v for k, v in data.file_dict.items() if "test" not in k}

    base_key = str(data.workspace_path)
    if instance_id is not None:
        base_key += f"_{instance_id}"
    unique_key = hashlib.md5(base_key.encode()).hexdigest()

    if len(show_files) > 0:
        with st.expander(f"Files in :blue[{replace_ep_path(data.workspace_path)}]"):
            code_tabs = st.tabs(show_files.keys())
            for ct, codename in zip(code_tabs, show_files.keys()):
                with ct:
                    st.code(
                        show_files[codename],
                        language=("python" if codename.endswith(".py") else "markdown"),
                        wrap_lines=True,
                        line_numbers=True,
                    )

            st.markdown("### Save All Files to Folder")
            target_folder = st.text_input("Enter target folder path:", key=f"save_folder_path_input_{unique_key}")

            if st.button("Save Files", key=f"save_files_button_{unique_key}"):
                if target_folder.strip() == "":
                    st.warning("Please enter a valid folder path.")
                else:
                    target_folder_path = Path(target_folder)
                    target_folder_path.mkdir(parents=True, exist_ok=True)
                    for filename, content in data.file_dict.items():
                        save_path = target_folder_path / filename
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        save_path.write_text(content, encoding="utf-8")
                    st.success(f"All files saved to: {target_folder}")
    else:
        st.markdown(f"No files in :blue[{replace_ep_path(data.workspace_path)}]")


# Helper functions
def show_text(text, lang=None):
    """显示文本代码块"""
    if lang:
        st.code(text, language=lang, wrap_lines=True)
    elif "\n" in text:
        st.code(text, language="python", wrap_lines=True)
    else:
        st.code(text, language="html", wrap_lines=True)


def highlight_prompts_uri(uri):
    """高亮 URI 的格式"""
    parts = uri.split(":")
    return f"**{parts[0]}:**:green[**{parts[1]}**]"


def llm_log_win(llm_d: list):
    for d in llm_d:
        if "debug_tpl" in d["tag"]:
            uri = d["obj"]["uri"]
            tpl = d["obj"]["template"]
            cxt = d["obj"]["context"]
            rd = d["obj"]["rendered"]
            with st.expander(highlight_prompts_uri(uri), expanded=False, icon="⚙️"):
                t1, t2, t3 = st.tabs([":green[**Rendered**]", ":blue[**Template**]", ":orange[**Context**]"])
                with t1:
                    show_text(rd)
                with t2:
                    show_text(tpl, lang="django")
                with t3:
                    st.json(cxt)
        elif "debug_llm" in d["tag"]:
            system = d["obj"].get("system", None)
            user = d["obj"]["user"]
            resp = d["obj"]["resp"]
            with st.expander(f"**LLM**", expanded=False, icon="🤖"):
                t1, t2, t3 = st.tabs([":green[**Response**]", ":blue[**User**]", ":orange[**System**]"])
                with t1:
                    try:
                        rdict = json.loads(resp)
                        if "code" in rdict:
                            code = rdict["code"]
                            st.markdown(":red[**Code in response dict:**]")
                            st.code(code, language="python", wrap_lines=True, line_numbers=True)
                            rdict.pop("code")
                        elif "spec" in rdict:
                            spec = rdict["spec"]
                            st.markdown(":red[**Spec in response dict:**]")
                            st.markdown(spec)
                            rdict.pop("spec")
                        else:
                            # show model codes
                            showed_keys = []
                            for k, v in rdict.items():
                                if k.startswith("model_") and k.endswith(".py"):
                                    st.markdown(f":red[**{k}**]")
                                    st.code(v, language="python", wrap_lines=True, line_numbers=True)
                                    showed_keys.append(k)
                            for k in showed_keys:
                                rdict.pop(k)
                        st.write(":red[**Other parts (except for the code or spec) in response dict:**]")
                        st.json(rdict)
                    except:
                        st.json(resp)
                with t2:
                    show_text(user)
                with t3:
                    show_text(system or "No system prompt available")


def hypothesis_win(data):
    st.code(str(data).replace("\n", "\n\n"), wrap_lines=True)


def exp_gen_win(data, llm_data=None):
    st.header("Exp Gen", divider="blue", anchor="exp-gen")
    if state.show_llm_log:
        llm_log_win(llm_data["no_tag"])
    st.subheader("Hypothesis")
    hypothesis_win(data["no_tag"].hypothesis)

    st.subheader("pending_tasks")
    for tasks in data["no_tag"].pending_tasks_list:
        task_win(tasks[0])
    st.subheader("Exp Workspace")
    workspace_win(data["no_tag"].experiment_workspace)


def evolving_win(data, key, llm_data=None):
    with st.container(border=True):
        if len(data) > 1:
            evo_id = st.slider("Evolving", 0, len(data) - 1, 0, key=key)
        elif len(data) == 1:
            evo_id = 0
        else:
            st.markdown("No evolving.")
            return

        if evo_id in data:
            if state.show_llm_log:
                llm_log_win(llm_data[evo_id])
            if data[evo_id]["evolving code"][0] is not None:
                st.subheader("codes")
                workspace_win(data[evo_id]["evolving code"][0], instance_id=key)
                fb = data[evo_id]["evolving feedback"][0]
                st.subheader("evolving feedback" + ("✅" if bool(fb) else "❌"))
                f1, f2, f3 = st.tabs(["execution", "return_checking", "code"])
                f1.code(fb.execution, wrap_lines=True)
                f2.code(fb.return_checking, wrap_lines=True)
                f3.code(fb.code, wrap_lines=True)
            else:
                st.write("data[evo_id]['evolving code'][0] is None.")
                st.write(data[evo_id])
        else:
            st.markdown("No evolving.")


def coding_win(data, llm_data: dict | None = None):
    st.header("Coding", divider="blue", anchor="coding")
    if llm_data is not None:
        common_llm_data = llm_data.pop("no_tag", [])
    evolving_data = {k: v for k, v in data.items() if isinstance(k, int)}
    task_set = set()
    for v in evolving_data.values():
        for t in v:
            if "Task" in t.split(".")[0]:
                task_set.add(t.split(".")[0])
    if task_set:
        # 新版存Task tag的Trace
        for task in task_set:
            st.subheader(task)
            task_data = {k: {a.split(".")[1]: b for a, b in v.items() if task in a} for k, v in evolving_data.items()}
            evolving_win(task_data, key=task, llm_data=llm_data if llm_data else None)
    else:
        # 旧版未存Task tag的Trace
        evolving_win(evolving_data, key="coding", llm_data=llm_data if llm_data else None)
    if state.show_llm_log:
        llm_log_win(common_llm_data)
    if "no_tag" in data:
        st.subheader("Exp Workspace (coding final)")
        workspace_win(data["no_tag"].experiment_workspace, instance_id="coding_dump")


def running_win(data, mle_score, llm_data=None):
    st.header("Running", divider="blue", anchor="running")
    if llm_data is not None:
        common_llm_data = llm_data.pop("no_tag", [])
    evolving_win(
        {k: v for k, v in data.items() if isinstance(k, int)}, key="running", llm_data=llm_data if llm_data else None
    )
    if state.show_llm_log:
        llm_log_win(common_llm_data)
    if "no_tag" in data:
        st.subheader("Exp Workspace (running final)")
        workspace_win(data["no_tag"].experiment_workspace, instance_id="running_dump")
        st.subheader("Result")
        st.write(data["no_tag"].result)
        st.subheader("MLE Submission Score" + ("✅" if (isinstance(mle_score, dict) and mle_score["score"]) else "❌"))
        if isinstance(mle_score, dict):
            st.json(mle_score)
        else:
            st.code(mle_score, wrap_lines=True)


def feedback_win(data, llm_data=None):
    data = data["no_tag"]
    st.header("Feedback" + ("✅" if bool(data) else "❌"), divider="orange", anchor="feedback")
    if state.show_llm_log and llm_data is not None:
        llm_log_win(llm_data["no_tag"])
    st.code(str(data).replace("\n", "\n\n"), wrap_lines=True)
    if data.exception is not None:
        st.markdown(f"**:red[Exception]**: {data.exception}")


def sota_win(data):
    st.header("SOTA Experiment", divider="rainbow", anchor="sota-exp")
    if data:
        st.markdown(f"**SOTA Exp Hypothesis**")
        hypothesis_win(data.hypothesis)
        st.markdown("**Exp Workspace**")
        workspace_win(data.experiment_workspace, instance_id="sota")
    else:
        st.markdown("No SOTA experiment.")


def main_win(data, llm_data=None):
    exp_gen_win(data["direct_exp_gen"], llm_data["direct_exp_gen"] if llm_data else None)
    if "coding" in data:
        coding_win(data["coding"], llm_data["coding"] if llm_data else None)
    if "running" in data:
        running_win(data["running"], data["mle_score"], llm_data=llm_data["running"] if llm_data else None)
    if "feedback" in data:
        feedback_win(data["feedback"], llm_data.get("feedback", None) if llm_data else None)
    if "record" in data and "SOTA experiment" in data["record"]:
        sota_win(data["record"]["SOTA experiment"])


def replace_ep_path(p: Path):
    # 替换workspace path为对应ep机器mount在ep03的path
    # TODO: FIXME: 使用配置项来处理
    match = re.search(r"ep\d+", str(state.log_folder))
    if match:
        ep = match.group(0)
        return Path(
            str(p).replace("repos/RD-Agent-Exp", f"repos/batch_ctrl/all_projects/{ep}").replace("/Data", "/data")
        )
    return p


def summarize_data():
    st.header("Summary", divider="rainbow")
    df = pd.DataFrame(
        columns=["Component", "Running Score", "Feedback", "e-loops", "Time", "Start Time (UTC+8)", "End Time (UTC+8)"],
        index=range(len(state.data) - 1),
    )

    for loop in range(len(state.data) - 1):
        loop_data = state.data[loop]
        df.loc[loop, "Component"] = loop_data["direct_exp_gen"]["no_tag"].hypothesis.component
        if state.times[loop]:
            df.loc[loop, "Time"] = str(sum((i.end - i.start for i in state.times[loop]), timedelta())).split(".")[0]
            df.loc[loop, "Start Time (UTC+8)"] = state.times[loop][0].start + timedelta(hours=8)
            df.loc[loop, "End Time (UTC+8)"] = state.times[loop][-1].end + timedelta(hours=8)
        if "running" in loop_data and "no_tag" in loop_data["running"]:
            if "mle_score" not in state.data[loop]:
                if "mle_score" in loop_data["running"]:
                    mle_score_txt = loop_data["running"]["mle_score"]
                    state.data[loop]["mle_score"] = extract_mle_json(mle_score_txt)
                    if state.data[loop]["mle_score"]["score"] is not None:
                        df.loc[loop, "Running Score"] = str(state.data[loop]["mle_score"]["score"])
                    else:
                        state.data[loop]["mle_score"] = mle_score_txt
                        df.loc[loop, "Running Score"] = "❌"
                else:
                    mle_score_path = (
                        replace_ep_path(loop_data["running"]["no_tag"].experiment_workspace.workspace_path)
                        / "mle_score.txt"
                    )
                    try:
                        mle_score_txt = mle_score_path.read_text()
                        state.data[loop]["mle_score"] = extract_mle_json(mle_score_txt)
                        if state.data[loop]["mle_score"]["score"] is not None:
                            df.loc[loop, "Running Score"] = str(state.data[loop]["mle_score"]["score"])
                        else:
                            state.data[loop]["mle_score"] = mle_score_txt
                            df.loc[loop, "Running Score"] = "❌"
                    except Exception as e:
                        state.data[loop]["mle_score"] = str(e)
                        df.loc[loop, "Running Score"] = "❌"
            else:
                if isinstance(state.data[loop]["mle_score"], dict):
                    df.loc[loop, "Running Score"] = str(state.data[loop]["mle_score"]["score"])
                else:
                    df.loc[loop, "Running Score"] = "❌"

        else:
            df.loc[loop, "Running Score"] = "N/A"

        if "coding" in loop_data:
            df.loc[loop, "e-loops"] = max(i for i in loop_data["coding"].keys() if isinstance(i, int)) + 1
        if "feedback" in loop_data:
            df.loc[loop, "Feedback"] = "✅" if bool(loop_data["feedback"]["no_tag"]) else "❌"
        else:
            df.loc[loop, "Feedback"] = "N/A"
    stat_t0, stat_t1 = st.columns(2)
    stat_t0.dataframe(df)

    def comp_stat_func(x: pd.DataFrame):
        total_num = x.shape[0]
        valid_num = x[x["Running Score"] != "N/A"].shape[0]
        avg_e_loops = x["e-loops"].mean()
        return pd.Series(
            {
                "Total": total_num,
                "Valid": valid_num,
                "Valid Rate": round(valid_num / total_num * 100, 2),
                "Avg e-loops": round(avg_e_loops, 2),
            }
        )

    comp_df = df.loc[:, ["Component", "Running Score", "e-loops"]].groupby("Component").apply(comp_stat_func)
    comp_df.loc["Total"] = comp_df.sum()
    comp_df.loc["Total", "Valid Rate"] = round(comp_df.loc["Total", "Valid"] / comp_df.loc["Total", "Total"] * 100, 2)
    comp_df["Valid Rate"] = comp_df["Valid Rate"].apply(lambda x: f"{x}%")
    comp_df.loc["Total", "Avg e-loops"] = round(df["e-loops"].mean(), 2)
    stat_t1.dataframe(comp_df)


def stdout_win(loop_id: int):
    stdout = load_stdout()
    if stdout.startswith("Please Set"):
        st.toast(stdout, icon="🟡")
        return
    start_index = stdout.find(f"Start Loop {loop_id}")
    end_index = stdout.find(f"Start Loop {loop_id + 1}")
    loop_stdout = remove_ansi_codes(stdout[start_index:end_index])
    with st.container(border=True):
        st.subheader(f"Loop {loop_id} stdout")
        pattern = f"Start Loop {loop_id}, " + r"Step \d+: \w+"
        matches = re.finditer(pattern, loop_stdout)
        step_stdouts = {}
        for match in matches:
            step = match.group(0)
            si = match.start()
            ei = loop_stdout.find(f"Start Loop {loop_id}", match.end())
            step_stdouts[step] = loop_stdout[si:ei].strip()

        for k, v in step_stdouts.items():
            with st.expander(k, expanded=False):
                st.code(v, language="log", wrap_lines=True)


# UI - Main
if state.data["competition"]:
    st.title(state.data["competition"])
    summarize_data()
    if len(state.data) > 2:
        loop_id = st.slider("Loop", 0, len(state.data) - 2, 0)
    else:
        loop_id = 0
    if state.show_stdout:
        stdout_win(loop_id)
    main_win(state.data[loop_id], state.llm_data[loop_id])
