#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILLS_REPO_ROOT = SKILL_ROOT.parent
# 「哪些文件是必需的」是一条规则，规则住在规则源里。
#
# 它此前住在 xsos-delivery-control（PRIVATE），于是 audit 在 CI 上根本跑不起来：
# 2026-09-06 首次真跑，两个仓库同时 FileNotFoundError，因为脚本回落到
# $HOME/work/gitee/xsos-delivery-control，而 runner 上那个路径不存在。
# 加 token 检出私有仓与「规则源公开仓库、别再加 token」的口径冲突。
#
# 切分依据：audit 只需要清单里的 path，repair/sync 才需要 template 指向的模板文件。
# 所以清单（规则）搬进本仓，模板（内容）仍留在治理仓。
REQUIRED_FILES_MANIFEST = Path(__file__).resolve().parent.parent / "references" / "required-files.json"
WBS_VALIDATOR = SKILLS_REPO_ROOT / "xsos-wbs-pack" / "scripts" / "validate_wbs_pack.py"

# 唯一权威源（顾昊 2026-10-16）：规则与模板只从线上 xsos-delivery-control 的 main 读。
# 本机克隆会过期，过期的克隆就是第二个权威源，所以默认不找、也不回退本机副本；
# 只有显式传 --delivery-control-root 才读本机，并在输出里标明「非权威源」。
DEFAULT_SOURCE_REPO = "xsosglobal/xsos-delivery-control"
DEFAULT_SOURCE_REF = "main"
SOURCE_REPO_ENV = "XSOS_DELIVERY_CONTROL_REPO"
SOURCE_REF_ENV = "XSOS_DELIVERY_CONTROL_REF"
# 旧版本按这个环境变量找本机克隆。现在它不再生效，设了就提示，避免有人以为还在读本机。
LEGACY_ROOT_ENV = "XSOS_DELIVERY_CONTROL_ROOT"
LOCAL_COPY_NOTICE = "使用本机副本，非权威源"


class SourceError(RuntimeError):
    """权威源读不到。调用方必须失败退出，不得改读本机副本。"""


@dataclass(frozen=True)
class OnlineSource:
    """经 `gh api` 读线上 delivery-control。仓库是私有的，需要 xsosglobal 组织权限和 gh 登录。"""

    repo: str = DEFAULT_SOURCE_REPO
    ref: str = DEFAULT_SOURCE_REF
    runner: Callable[..., subprocess.CompletedProcess] = field(default=subprocess.run, compare=False, repr=False)

    authoritative = True

    @classmethod
    def from_env(cls, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> "OnlineSource":
        return cls(
            repo=os.environ.get(SOURCE_REPO_ENV) or DEFAULT_SOURCE_REPO,
            ref=os.environ.get(SOURCE_REF_ENV) or DEFAULT_SOURCE_REF,
            runner=runner,
        )

    @property
    def label(self) -> str:
        return f"github:{self.repo}@{self.ref}"

    def read(self, rel_path: str) -> str:
        endpoint = f"repos/{self.repo}/contents/{rel_path}?ref={self.ref}"
        command = ["gh", "api", endpoint, "-H", "Accept: application/vnd.github.raw"]
        try:
            result = self.runner(command, capture_output=True, text=True, timeout=30, check=False)
        except FileNotFoundError as exc:
            raise SourceError("找不到 gh 命令。先安装 GitHub CLI 并执行 gh auth login。") from exc
        except subprocess.TimeoutExpired as exc:
            raise SourceError(f"读取 {self.label}:{rel_path} 超时（30 秒），检查网络后重试。") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            reason = detail[-1] if detail else f"退出码 {result.returncode}"
            if "404" in reason or "Not Found" in reason:
                raise SourceError(
                    f"{self.label} 里没有 {rel_path}，或当前 gh 账号没有 xsosglobal 组织权限（私有仓库对无权限账号同样返回 404）：{reason}"
                )
            raise SourceError(f"读取 {self.label}:{rel_path} 失败（先确认 gh auth status 已登录且有组织权限）：{reason}")
        return result.stdout


@dataclass(frozen=True)
class LocalSource:
    """显式指定的本机副本。只给测试和离线排查用，输出里一律标明非权威。"""

    root: Path

    authoritative = False

    @property
    def label(self) -> str:
        return f"{self.root}（{LOCAL_COPY_NOTICE}）"

    def read(self, rel_path: str) -> str:
        path = self.root / rel_path
        if not path.is_file():
            raise SourceError(f"本机副本 {self.root} 里没有 {rel_path}（{LOCAL_COPY_NOTICE}）")
        return path.read_text(encoding="utf-8")


def resolve_source(delivery_control_root: Path | str | None = None,
                   runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
    if delivery_control_root:
        return LocalSource(Path(delivery_control_root).expanduser().resolve())
    return OnlineSource.from_env(runner=runner)


@dataclass
class GuardReport:
    status: str
    root: str
    missing_required: list[str]
    warnings: list[str]
    created: list[str]
    validator_status: str | None = None
    validator_output: str | None = None
    source: str | None = None
    source_authoritative: bool | None = None
    template_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "status": self.status,
            "root": self.root,
            "missing_required": self.missing_required,
            "warnings": self.warnings,
            "created": self.created,
            "validator_status": self.validator_status,
            "validator_output": self.validator_output,
        }
        if self.source is not None:
            data["source"] = self.source
            data["source_authoritative"] = self.source_authoritative
            data["template_missing"] = self.template_missing
        return data


@dataclass(frozen=True)
class RequiredFile:
    path: str
    template: str | None = None


def load_required_files(delivery_control_root: Path | str | None = None) -> list[RequiredFile]:
    """读必需文件清单。清单在本仓，与 delivery-control 是否可达无关；参数只为兼容旧调用方。"""
    manifest_path = REQUIRED_FILES_MANIFEST
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: list[RequiredFile] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("path"):
            raise ValueError(f"Invalid required file spec in {manifest_path}: {item!r}")
        files.append(RequiredFile(path=str(item["path"]), template=item.get("template")))
    return files


def load_template(source, spec: RequiredFile) -> str:
    """source 是 OnlineSource/LocalSource；传路径视为显式本机副本。读不到抛 SourceError。"""
    if not spec.template:
        return "# TODO\n"
    if isinstance(source, (str, Path)):
        source = LocalSource(Path(source).expanduser().resolve())
    return source.read(spec.template)


# 双语规则文件协议，与 dsh-delivery lib/rule-language.js 的 ruleVersions 一致：
# 同一文件里中文区在前、英文区在后，区外只允许文件标题、「## 中文」「## English」三行。
RULE_MARKERS = ("<!-- xsos-rule:zh -->", "<!-- /xsos-rule:zh -->", "<!-- xsos-rule:en -->", "<!-- /xsos-rule:en -->")


def rule_versions(body: str, path: str = "rule") -> dict[str, str]:
    def invalid(reason: str) -> None:
        raise ValueError(f"双语规则格式错误：{path}；{reason}")

    lines = body.splitlines(keepends=True)
    events: list[tuple[str, int]] = []
    fence: str | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        token = ""
        if indent <= 3:
            for char in ("`", "~"):
                count = len(stripped) - len(stripped.lstrip(char))
                if count >= 3:
                    token = char * count
                    break
        if token:
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not stripped[len(token):].strip():
                fence = None
            continue
        if fence is None and line.strip() in RULE_MARKERS:
            events.append((line.strip(), index))
    if len(events) != 4 or any(marker != RULE_MARKERS[i] for i, (marker, _) in enumerate(events)):
        invalid("需要唯一完整的中文区和英文区，中文在前")
    a, b, c, d = (index for _, index in events)
    zh = "".join(lines[a + 1:b]).strip()
    en = "".join(lines[c + 1:d]).strip()
    if not zh or not en:
        invalid("中文区和英文区都不能为空")
    outside = [line.strip() for line in lines[:a] + lines[b + 1:c] + lines[d + 1:] if line.strip()]
    if len(outside) != 3 or not outside[0].startswith("# ") or outside[1] != "## 中文" or outside[2] != "## English":
        invalid("区外仅允许文件标题、中文标题和English标题")
    return {"zh": zh, "en": en}


def _rel_exists(root: Path, rel_path: str) -> bool:
    return (root / rel_path).exists()


def _read_text(root: Path, rel_path: str) -> str:
    path = root / rel_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def audit_project(root: Path | str, delivery_control_root: Path | str | None = None) -> GuardReport:
    """只核对必需文件是否存在。不读 delivery-control，所以 CI 上无需任何凭据。

    delivery_control_root 只为兼容旧调用方保留，不起作用。
    """
    root_path = Path(root).resolve()
    required_files = load_required_files()
    missing = [spec.path for spec in required_files if not _rel_exists(root_path, spec.path)]
    warnings: list[str] = []

    if not _rel_exists(root_path, "module.yaml"):
        warnings.append("module.yaml is absent; required only for runtime modules.")

    standards = _read_text(root_path, "docs/standards/README.md").lower()
    if standards and "xsos-delivery-control" not in standards and "delivery-control" not in standards:
        warnings.append("docs/standards/README.md should reference xsos-delivery-control global standards.")

    change_control = _read_text(root_path, "docs/change-control.md").lower()
    if change_control and "changelog" not in change_control:
        warnings.append("docs/change-control.md should mention CHANGELOG update rules.")

    status = "pass" if not missing else "fail"
    return GuardReport(
        status=status,
        root=str(root_path),
        missing_required=missing,
        warnings=warnings,
        created=[],
    )


def sync_project(root: Path | str, source=None, check: bool = False,
                 delivery_control_root: Path | str | None = None) -> GuardReport:
    """对照权威源补齐必需文件。

    模板是起步脚手架，项目建好后归项目自己维护，所以已存在的文件一律不改、不比对。
    check=True 只报告，不写任何文件；同时核对清单里每个模板在权威源里确实存在，
    清单与治理仓脱节时能当场发现。权威源读不到时抛 SourceError，不回退本机副本。
    """
    if source is None:
        source = resolve_source(delivery_control_root)
    root_path = Path(root).resolve()
    specs = load_required_files()
    created: list[str] = []
    template_missing: list[str] = []
    bodies: dict[str, str] = {}

    errors: list[SourceError] = []
    templated = [spec for spec in specs if spec.template]

    def fetch(spec: RequiredFile):
        try:
            return spec, load_template(source, spec), None
        except SourceError as exc:
            return spec, None, exc

    # 每次 gh api 约 2 秒，19 个模板串行要 40 多秒；并发读，结果按清单顺序处理。
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, templated))
    for spec, body, exc in results:
        if exc is None:
            bodies[spec.path] = body
        else:
            errors.append(exc)
            template_missing.append(f"{spec.template}：{exc}")
    # 一个模板都读不到，多半是没登录、没权限或离线：整体失败，不出半截报告。
    # 个别模板读不到才是清单与治理仓脱节，逐条记下。
    if errors and not bodies:
        raise errors[0]

    if not check:
        for spec in specs:
            path = root_path / spec.path
            if path.exists():
                continue
            if spec.template and spec.path not in bodies:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(bodies.get(spec.path, "# TODO\n"), encoding="utf-8")
            created.append(spec.path)

    report = audit_project(root_path)
    report.created = created
    report.source = source.label
    report.source_authoritative = source.authoritative
    report.template_missing = template_missing
    if not source.authoritative:
        report.warnings.insert(0, f"{LOCAL_COPY_NOTICE}：{source.label}")
    if template_missing:
        report.status = "fail"
    elif created and not report.missing_required:
        report.status = "repaired"
    return report


def repair_project(root: Path | str, delivery_control_root: Path | str | None = None, source=None) -> GuardReport:
    """旧命令名，行为与 sync 相同。"""
    return sync_project(root, source=source, check=False, delivery_control_root=delivery_control_root)


def verify_project(root: Path | str, delivery_control_root: Path | str | None = None) -> GuardReport:
    root_path = Path(root).resolve()
    report = audit_project(root_path)

    if WBS_VALIDATOR.exists() and (root_path / "docs" / "wbs").exists():
        result = subprocess.run(
            [sys.executable, str(WBS_VALIDATOR), str(root_path / "docs" / "wbs")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        report.validator_status = "pass" if result.returncode == 0 else "fail"
        report.validator_output = result.stdout.strip()
        if result.returncode != 0:
            report.status = "fail"
    else:
        report.validator_status = "skipped"
        report.validator_output = "WBS validator or docs/wbs not found."

    return report


def read_rule(source, rel_path: str, lang: str = "both") -> str:
    """从权威源读一份规则。双语规则文件按协议校验并取对应语言区，其余文件原样返回。"""
    body = source.read(rel_path)
    if not any(marker in body for marker in RULE_MARKERS):
        return body
    versions = rule_versions(body, rel_path)
    if lang == "both":
        return f"## 中文\n\n{versions['zh']}\n\n## English\n\n{versions['en']}\n"
    return versions[lang] + "\n"


def print_report(report: GuardReport) -> None:
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None,
         runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Audit, sync, or verify XSOS project standards against the online delivery-control source.")
    parser.add_argument("mode", choices=["audit", "repair", "sync", "verify", "rule"])
    parser.add_argument("target", nargs="?", default=".", help="项目根目录；rule 模式下是规则路径，例如 rules/wbs-rule.md")
    parser.add_argument("--check", action="store_true", help="sync 只报告差异，不写文件")
    parser.add_argument("--lang", choices=["zh", "en", "both"], default="both", help="rule 模式输出哪个语言区")
    parser.add_argument("--delivery-control-root", default=None,
                        help=f"显式改读本机副本（{LOCAL_COPY_NOTICE}），仅供测试与离线排查")
    args = parser.parse_args(argv)

    if os.environ.get(LEGACY_ROOT_ENV) and not args.delivery_control_root:
        print(f"提示：{LEGACY_ROOT_ENV} 已不再生效，规则与模板只从线上权威源读取。", file=sys.stderr)

    if args.mode == "audit":
        report = audit_project(Path(args.target))
    elif args.mode == "verify":
        report = verify_project(Path(args.target))
    else:
        source = resolve_source(args.delivery_control_root, runner=runner)
        if not source.authoritative:
            print(f"注意：{LOCAL_COPY_NOTICE}（{source.root}）。", file=sys.stderr)
        try:
            if args.mode == "rule":
                sys.stdout.write(read_rule(source, args.target, args.lang))
                return 0
            if args.mode == "sync":
                report = sync_project(Path(args.target), source, check=args.check)
            else:
                report = repair_project(Path(args.target), source)
        except (SourceError, ValueError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2

    print_report(report)
    return 0 if report.status in {"pass", "repaired"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
