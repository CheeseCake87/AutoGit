import json
import os
import re
import typing as t

from .environment import Environment
from .resources import Resources
from .terminator import Terminator
from .the_nightman import Supervisorctl
from .tools import Tools


def _failed(outputs: t.List[str], fail_on: t.List[str] = None):
    complete = ""
    for output in outputs:
        complete += output

    for fail in fail_on:
        if fail in complete:
            return True
    return False


class GitDeploy:
    dummy_command = "echo 'Waiting for command to be set...'"
    supervisorctl_process: t.Optional[Supervisorctl] = None

    def __init__(self):
        self.env = Environment()
        self.supervisorctl_process = Supervisorctl()
        self.read_conf()
        if not self.env.satellite_ini.exists():
            self.write_satellite_ini()

    def init_supervisorctl(self):
        self.supervisorctl_process.start()

    def _parse_command(self) -> str:
        command = "echo 'Waiting for command to be set...'"
        if self.env.repo_venv_bin.exists():
            os.listdir(self.env.repo_venv_bin)
            if self.conf.get("COMMAND"):
                start_command = self.conf.get("COMMAND").split(" ")[0]
                if start_command in os.listdir(self.env.repo_venv_bin):
                    command = f"venv/bin/{self.conf.get('COMMAND')}"
        return command

    def get_repo_contents(self) -> t.List[str]:
        return os.listdir(self.env.repo_dir)

    def supervisor_update(self):
        with Terminator("venv/bin/supervisorctl -c supervisor/supervisord.conf") as ctl:
            ctl("update")

    def set_conf(self, key: str, value: t.Any, write: bool = False):
        if key not in self.conf:
            raise KeyError(f"Key '{key}' not found in conf file")

        self.conf[key] = value

        if write:
            self.write_conf()

    def read_conf(self):
        with open(self.env.conf_file, "r") as conf:
            self.conf = json.load(conf)

    def write_conf(self, new_conf: t.Optional[dict] = None):
        with open(self.env.conf_file, "w") as conf:
            if new_conf:
                json.dump(new_conf, conf, indent=4)
            else:
                json.dump(self.conf, conf, indent=4)

    def _write_dot_git_config(self, new_url):
        if self.env.repo_dot_git_config.exists():
            with open(self.env.repo_dot_git_config, "r") as old_config:
                old_config_ = old_config.read()
                with open(self.env.repo_dot_git_config, "w") as new_config:
                    new_config_ = re.sub(r"(?<=url = ).*", new_url, old_config_)
                    new_config.write(new_config_)

    def set_dot_git_config_with_token(self) -> bool:
        git_url = self.conf.get("GIT_URL")
        token_name = self.conf.get("GIT_TOKEN_NAME")
        token = self.conf.get("GIT_TOKEN")

        new_git = git_url.replace("https://", f"https://{token_name}:{token}@")
        self.set_conf("GIT", new_git, write=True)
        self._write_dot_git_config(new_git)
        return True

    def set_dot_git_config_without_token(self) -> bool:
        git_url = self.conf.get("GIT_URL")
        self.set_conf("GIT", git_url, write=True)
        self._write_dot_git_config(git_url)
        return True

    def write_satellite_ini(self):
        with open(self.env.satellite_ini, "w") as ini:
            ini.write(
                Resources.generate_satellite_ini(
                    app="satellite",
                    command=self._parse_command(),
                    user=self.env.os.user,
                    log_location=self.env.log_file,
                    working_directory=self.env.repo_dir
                )
            )
        self.supervisor_update()

    def set_tokens(self):
        self.set_conf("T1", Tools.generate_random_token(24))
        self.set_conf("T2", Tools.generate_random_token(24))
        self.set_conf("FIRST_RUN", False)
        self.write_conf()

    def clone_repo(self):
        with Terminator("git", type_="pexpect") as git:
            return git(
                f"clone {self.conf.get('GIT')} {self.env.repo_dir}",
                expects={"Username": None}
            )

    def create_venv(self):
        with Terminator("python3") as python:
            python(f"-m venv {self.env.repo_venv_bin.parent}")

    def install_requirements(self):
        if self.env.repo_pip.exists():
            with Terminator("venv/bin/pip", working_directory=self.env.repo_dir) as pip:
                pip(f"install -r {self.env.repo_requirements_file}")

    def check_installed_packages(self):
        if self.env.repo_pip.exists():
            with Terminator("venv/bin/pip", working_directory=self.env.repo_dir, log=False) as pip:
                return pip(f"freeze")

    def update_repo(self):
        with Terminator("git") as git:
            return git("pull", working_directory=self.env.repo_dir)

    def destroy_repo(self):
        with Terminator("rm") as rm:
            rm(f"-rf {self.env.repo_dir}")
            self.env.repo_dir.mkdir(exist_ok=True)

    def destroy_venv(self):
        with Terminator("rm") as rm:
            rm(f"-rf {self.env.repo_venv_bin.parent}")

    def status_satellite(self):
        self.supervisorctl_process.send("status satellite")

        before = self.supervisorctl_process.before
        if isinstance(before, bytes):
            if "RUNNING" in before.decode("utf-8"):
                return True
        return False
        #
        # with Terminator(
        #         "venv/bin/supervisorctl -c supervisor/supervisord.conf",
        #         type_="pexpect_supervisor",
        #         log=False
        # ) as ctl:
        #     output = ctl("status satellite")
        #
        # for line in output:
        #     if "FATAL" in line:
        #         return False
        # return True

    def start_satellite(self):
        if self.conf.get("COMMAND") is not None:
            self.supervisorctl_process.send("update all")
            self.supervisorctl_process.send("start satellite")
            #
            # with Terminator("venv/bin/supervisorctl -c supervisor/supervisord.conf") as ctl:
            #     ctl("start satellite")

    def stop_satellite(self):
        if self.conf.get("COMMAND") is not None:
            self.supervisorctl_process.send("stop satellite")
            #
            # with Terminator("venv/bin/supervisorctl -c supervisor/supervisord.conf") as ctl:
            #     ctl("stop satellite")

    def restart_satellite(self):
        if self.conf.get("COMMAND") is not None:
            self.supervisorctl_process.send("restart satellite")
            #
            # with Terminator("venv/bin/supervisorctl -c supervisor/supervisord.conf") as ctl:
            #     ctl("restart satellite")

    def read_logs(self) -> list:
        logs = self.env.log_file.read_text().split("\n")
        return [x for x in logs if x]

    def clear_logs(self):
        self.env.log_file.unlink()
        self.env.log_file.touch()