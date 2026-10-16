"""Backend and argument validation for IQ-TREE 2 GUI. No third-party dependencies."""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Callable
import os
import re
import shlex
import shutil
import subprocess
import sys


@dataclass
class AnalysisConfig:
    alignment: str = ""
    output_dir: str = ""
    prefix: str = ""
    partitions: str = ""
    partition_scheme: str = "proportional"   # proportional (-p), equal (-q), unlinked (-Q)
    model_mode: str = "MFP"                # MFP, MF, CUSTOM
    fixed_model: str = "GTR+F+G4"
    merge_partitions: bool = False
    seq_type: str = "AUTO"                 # AUTO, DNA, AA, CODON, CODON5, BIN, MORPH
    support_mode: str = "UFBoot"            # UFBoot, Standard, None
    bootstrap_reps: int = 1000
    alrt: bool = True
    alrt_reps: int = 1000
    bnni: bool = False
    threads: str = "AUTO"
    seed: str = "12345"
    outgroup: str = ""
    redo: bool = False
    extra: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisConfig":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def validate(self) -> None:
        if not self.alignment.strip() or not Path(self.alignment).is_file():
            raise ValueError("정렬된 서열 파일을 선택하십시오 (FASTA, PHYLIP, NEXUS 등).")
        if not self.output_dir.strip():
            raise ValueError("결과 저장 폴더를 지정하십시오.")
        if Path(self.output_dir).exists() and not Path(self.output_dir).is_dir():
            raise ValueError("결과 경로가 폴더가 아닙니다.")
        if not self.prefix or self.prefix in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', self.prefix):
            raise ValueError("분석 이름에 사용할 수 없는 문자가 있습니다.")
        if self.partitions and not Path(self.partitions).is_file():
            raise ValueError("Partition 파일을 찾을 수 없습니다.")
        if self.partitions and self.partition_scheme not in ("proportional", "equal", "unlinked"):
            raise ValueError("Partition 분석 방식을 확인하십시오.")
        if self.model_mode not in ("MFP", "MF", "CUSTOM"):
            raise ValueError("모델 선택 방식을 확인하십시오.")
        if self.model_mode == "CUSTOM" and not self.fixed_model.strip():
            raise ValueError("고정 진화모델을 입력하십시오.")
        if self.merge_partitions and (not self.partitions or self.model_mode != "MFP"):
            raise ValueError("Partition 병합은 Partition 파일과 ModelFinder + ML을 선택해야 합니다.")
        if self.seq_type not in ("AUTO", "DNA", "AA", "CODON", "CODON5", "BIN", "MORPH"):
            raise ValueError("서열 유형이 올바르지 않습니다.")
        if self.support_mode not in ("UFBoot", "Standard", "None"):
            raise ValueError("Bootstrap 방식을 확인하십시오.")
        if self.model_mode == "MF" and (self.support_mode != "None" or self.alrt):
            raise ValueError("ModelFinder만 실행할 때는 Bootstrap과 SH-aLRT를 끄십시오.")
        if self.support_mode == "UFBoot" and int(self.bootstrap_reps) < 1000:
            raise ValueError("UFBoot은 최소 1,000회 반복해야 합니다.")
        if self.support_mode == "Standard" and int(self.bootstrap_reps) < 100:
            raise ValueError("Standard bootstrap은 100회 이상을 권장합니다 (여기서는 최소 100회).")
        if self.alrt and int(self.alrt_reps) < 1000:
            raise ValueError("SH-aLRT는 최소 1,000회 반복해야 합니다.")
        if self.bnni and self.support_mode != "UFBoot":
            raise ValueError("BNNI 옵션은 UFBoot 사용 시에만 적용합니다.")
        if self.threads != "AUTO" and (not self.threads.isdigit() or int(self.threads) < 1):
            raise ValueError("CPU 스레드는 AUTO 또는 1 이상의 정수여야 합니다.")
        if self.seed and (not self.seed.isdigit() or int(self.seed) < 1):
            raise ValueError("Random seed는 양의 정수여야 합니다.")
        if self.extra:
            try:
                split_extra(self.extra)
            except ValueError as ex:
                raise ValueError(f"추가 옵션 형식 오류: {ex}") from ex

    def args(self, path_map: Callable[[str], str] | None = None) -> list[str]:
        self.validate()
        transform = path_map or (lambda p: p)
        output_prefix = str(Path(self.output_dir) / self.prefix)
        args = ["-s", transform(str(Path(self.alignment).resolve()))]
        if self.seq_type != "AUTO":
            args += ["-st", self.seq_type]
        if self.partitions:
            flag = {"proportional": "-p", "equal": "-q", "unlinked": "-Q"}[self.partition_scheme]
            args += [flag, transform(str(Path(self.partitions).resolve()))]
        if self.model_mode == "CUSTOM":
            args += ["-m", self.fixed_model.strip()]
        elif self.model_mode == "MF":
            args += ["-m", "MF"]
        else:
            args += ["-m", "MFP+MERGE" if self.merge_partitions else "MFP"]
        if self.support_mode == "UFBoot":
            args += ["-B", str(self.bootstrap_reps)]
            if self.bnni:
                args += ["--bnni"]
        elif self.support_mode == "Standard":
            args += ["-b", str(self.bootstrap_reps)]
        if self.alrt:
            args += ["--alrt", str(self.alrt_reps)]
        args += ["-T", str(self.threads)]
        if self.seed:
            args += ["-seed", str(self.seed)]
        if self.outgroup.strip():
            args += ["-o", self.outgroup.strip()]
        if self.redo:
            args += ["--redo"]
        args += ["--prefix", transform(str(Path(output_prefix).resolve()))]
        args += split_extra(self.extra)
        return args

    def to_dict(self):
        return asdict(self)


def split_extra(raw: str) -> list[str]:
    """Parse optional IQ-TREE flags, not through a shell. Quoted arguments permitted."""
    return shlex.split(raw.strip(), posix=True) if raw.strip() else []


def available_windows_binaries() -> list[str]:
    names = ["iqtree2.exe", "iqtree2", "iqtree2-omp.exe", "iqtree2-avx2.exe", "iqtree2-avx.exe"]
    local = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    candidates = [local / "bin" / n for n in names] + [local / n for n in names]
    found = [str(p) for p in candidates if p.is_file()]
    for name in names:
        result = shutil.which(name)
        if result and result not in found:
            found.append(result)
    return found


def wsl_distributions() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        process = subprocess.run(["wsl.exe", "-l", "-q"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        # `wsl -l -q` on Korean/English Windows may be UTF-16-LE.
        raw = process.stdout
        if b"\x00" in raw:
            output = raw.decode("utf-16-le", errors="replace")
        else:
            output = raw.decode("utf-8", errors="replace")
        return [x.lstrip("\ufeff").strip() for x in output.splitlines() if x.lstrip("\ufeff").strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def to_wsl_path(path: str, distro: str = "") -> str:
    """Use WSL's own path conversion, avoiding guessed /mnt drive locations."""
    command = ["wsl.exe"]
    if distro.strip():
        command += ["-d", distro.strip()]
    command += ["-e", "wslpath", "-a", "-u", path]
    try:
        res = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12)
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise ValueError(f"WSL 경로를 변환하지 못했습니다: {ex}") from ex
    if res.returncode != 0 or not res.stdout.strip():
        raise ValueError(f"WSL 경로 변환 실패: {path}\n{res.stderr.strip()}")
    return res.stdout.strip()


def command_string(command: list[str]) -> str:
    # For presentation/reproduction only; the program never uses a shell to run it.
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def build_command(config: AnalysisConfig, mode: str, binary: str, distro: str = "") -> tuple[list[str], str]:
    if mode == "Windows":
        target = binary.strip() or (available_windows_binaries() or [""])[0]
        if not target:
            raise ValueError("IQ-TREE 2 실행파일(iqtree2.exe)을 지정하십시오. 홈페이지에서 별도 설치해야 합니다.")
        command = [target] + config.args()
        return command, command_string(command)
    if mode == "WSL":
        target = binary.strip() or "iqtree2"
        cache: dict[str, str] = {}
        def translate(path: str) -> str:
            if path not in cache:
                cache[path] = to_wsl_path(path, distro)
            return cache[path]
        iqargs = config.args(translate)
        cmd = ["wsl.exe"]
        if distro.strip():
            cmd += ["-d", distro.strip()]
        # Preserve argv, including alignment paths that contain whitespace.
        cmd += ["-e", "bash", "-lc", 'printf "__IQTREE_GUI_PID__=%s\\n" "$$"; exec "$@"', "iqtree-gui", target] + iqargs
        return cmd, command_string(cmd)
    raise ValueError("실행 환경은 Windows 또는 WSL이어야 합니다.")


def stop_wsl_pid(distro: str, pid: int) -> None:
    if not pid or pid < 1:
        return
    cmd = ["wsl.exe"]
    if distro.strip():
        cmd += ["-d", distro.strip()]
    cmd += ["-e", "kill", "-TERM", str(pid)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
