import os
import shlex
import shutil
import subprocess
from datetime import datetime
import re
from flask import Flask, render_template, request, jsonify

try:
    import psutil
except ImportError:
    psutil = None

app = Flask(__name__)

HOME = os.path.expanduser("~")

# Command implementations
def cmd_ls(args):
    path = args[0] if args else '.'
    try:
        entries = os.listdir(path)
        entries.sort()
        return "\n".join([f"{name}/" if os.path.isdir(os.path.join(path, name)) else name for name in entries])
    except Exception as e:
        return f"ls: {e}"

def cmd_cd(args):
    path = args[0] if args else HOME
    try:
        os.chdir(os.path.expanduser(path))
        return f"Changed directory to {os.getcwd()}"
    except Exception as e:
        return f"cd: {e}"

def cmd_pwd(args):
    return os.getcwd()

def cmd_mkdir(args):
    if not args:
        return "mkdir: missing operand"
    out = ""
    for d in args:
        try:
            os.makedirs(d, exist_ok=False)
            out += f"Directory '{d}' created\n"
        except FileExistsError:
            out += f"mkdir: cannot create directory '{d}': File exists\n"
        except Exception as e:
            out += f"mkdir: {e}\n"
    return out

def cmd_rm(args):
    if not args:
        return "rm: missing operand"
    out = ""
    for path in args:
        try:
            if os.path.isdir(path):
                out += f"rm: '{path}' is a directory (use rmdir)\n"
            else:
                os.remove(path)
                out += f"Removed file {path}\n"
        except Exception as e:
            out += f"rm: {e}\n"
    return out

def cmd_rmdir(args):
    if not args:
        return "rmdir: missing operand"
    out = ""
    for d in args:
        try:
            os.rmdir(d)
            out += f"Removed directory {d}\n"
        except Exception as e:
            out += f"rmdir: {e}\n"
    return out

def cmd_touch(args):
    if not args:
        return "touch: missing file operand"
    out = ""
    for f in args:
        try:
            with open(f, 'a'):
                os.utime(f, None)
            out += f"Touched file {f}\n"
        except Exception as e:
            out += f"touch: {e}\n"
    return out

def cmd_cat(args):
    if not args:
        return "cat: missing file operand"
    out = ""
    for f in args:
        if not os.path.exists(f):
            out += f"cat: {f}: No such file\n"
            continue
        try:
            with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                out += fh.read()
        except Exception as e:
            out += f"cat: {e}\n"
    return out

def cmd_echo(args):
    return ' '.join(args)

def cmd_mv(args):
    if len(args) != 2:
        return "mv: need source and destination"
    try:
        shutil.move(args[0], args[1])
        return "Moved"
    except Exception as e:
        return f"mv: {e}"

def cmd_cp(args):
    if len(args) != 2:
        return "cp: need source and destination"
    src = os.path.abspath(args[0])
    dest = os.path.abspath(args[1])
    if not os.path.isfile(src):
        return f"cp: source file does not exist: {src}"
    if not os.path.exists(dest):
        return f"cp: destination does not exist: {dest}"
    try:
        shutil.copy2(src, dest)
        return f"Copied {src} to {dest}"
    except Exception as e:
        return f"cp: {e}"

def cmd_cpu(args):
    if psutil:
        return f"CPU cores: {psutil.cpu_count(logical=True)} | CPU usage: {psutil.cpu_percent(interval=0.5)}%"
    return "cpu: detailed stats require psutil"

def cmd_mem(args):
    if psutil:
        vm = psutil.virtual_memory()
        return f"Total: {vm.total} Available: {vm.available} Used: {vm.used} Percent: {vm.percent}%"
    return "mem: detailed stats require psutil"

def cmd_ps(args):
    if not psutil:
        return "ps: requires psutil"
    keyword = args[0] if args else None
    entries = []
    for p in psutil.process_iter(['pid', 'name', 'username']):
        try:
            info = p.info
            if keyword and keyword.lower() not in str(info.get('name', '')).lower():
                continue
            entries.append(f"{info.get('pid')} {info.get('username')} {info.get('name')}")
        except Exception:
            continue
    return "\n".join(entries)

def cmd_man(args):
    man_pages = {
        "ls": "ls - list directory contents",
        "cd": "cd - change directory",
        "pwd": "pwd - print current directory",
        "mkdir": "mkdir - create directory",
        "rm": "rm - remove file",
        "rmdir": "rmdir - remove directory",
        "touch": "touch - create empty file",
        "cat": "cat - display file content",
        "echo": "echo - display message",
        "mv": "mv - move/rename files",
        "cp": "cp - copy files",
        "cpu": "cpu - show CPU usage",
        "mem": "mem - show memory usage",
        "ps": "ps - show running processes",
        "uptime": "uptime - show system uptime"
    }
    if not args:
        return "\n".join([f"{k}: {v}" for k,v in man_pages.items()])
    return man_pages.get(args[0], f"man: no entry for {args[0]}")

def cmd_uptime(args):
    try:
        if psutil:
            boot = datetime.fromtimestamp(psutil.boot_time())
            return f"System boot: {boot}"
        out = subprocess.check_output(['uptime']).decode()
        return out.strip()
    except Exception:
        return "uptime: unable to determine uptime"

# File write function used for cat > and cat >>
def cat_write(filename, content, append=False):
    mode = 'a' if append else 'w'
    try:
        with open(filename, mode, encoding='utf-8') as f:
            f.write(content)
        return f"Content {'appended to' if append else 'written to'} {filename}"
    except Exception as e:
        return f"cat_write error: {e}"

# NLP parser function to handle natural language to shell command mapping
def ai_parse_command(nl_command):
    nl_lower = nl_command.lower()
    if "present working directory" in nl_lower:
        return "pwd"
    elif "list files" in nl_lower or "show files" in nl_lower:
        return "ls"
    elif "create folder" in nl_lower:
        folder = re.search(r'create folder (\S+)', nl_command)
        if folder:
            return f"mkdir {folder.group(1)}"
    elif "remove folder" in nl_lower or "delete folder" in nl_lower or "remove directory" in nl_lower:
        folder = re.search(r'(?:remove|delete) (?:folder|directory) (\S+)', nl_command)
        if folder:
            return f"rmdir {folder.group(1)}"
    elif "remove file" in nl_lower or "delete file" in nl_lower:
        file = re.search(r'(?:remove|delete) file (\S+)', nl_command)
        if file:
            return f"rm {file.group(1)}"
    elif "create file" in nl_lower:
        file = re.search(r'create file (\S+)', nl_command)
        if file:
            return f"touch {file.group(1)}"
    elif "move" in nl_lower and "into" in nl_lower:
        match = re.search(r'move (\S+) into (\S+)', nl_command)
        if match:
            return f"mv {match.group(1)} {match.group(2)}/"
    elif "copy" in nl_lower and "from" in nl_lower and "to" in nl_lower:
        match = re.search(r'copy (\S+) from (\S+) to (\S+)', nl_command)
        if match:
            src_file = match.group(1)
            src_dir = match.group(2)
            dest_dir = match.group(3)
            if os.path.isabs(src_dir):
                full_src = os.path.join(src_dir, src_file)
            else:
                full_src = os.path.join(os.getcwd(), src_dir, src_file)
            full_src = os.path.abspath(full_src)
            if dest_dir.lower() in ['current', 'current directory', 'here', '.']:
                full_dest = os.getcwd()
            else:
                full_dest = os.path.abspath(dest_dir)
            return f'cp "{full_src}" "{full_dest}"'
    elif "show content" in nl_lower or "display content" in nl_lower:
        file = re.search(r'content of (\S+)', nl_command)
        if file:
            return f"cat {file.group(1)}"
    elif "cpu info" in nl_lower:
        return "cpu"
    elif "memory info" in nl_lower or "ram info" in nl_lower:
        return "mem"
    elif "uptime" in nl_lower:
        return "uptime"
    elif "processes" in nl_lower:
        return "ps"
    return nl_command

# Command dictionary mapping commands to functions
COMMANDS = {
    'ls': cmd_ls,
    'cd': cmd_cd,
    'pwd': cmd_pwd,
    'mkdir': cmd_mkdir,
    'rm': cmd_rm,
    'rmdir': cmd_rmdir,
    'touch': cmd_touch,
    'cat': cmd_cat,
    'echo': cmd_echo,
    'mv': cmd_mv,
    'cp': cmd_cp,
    'cpu': cmd_cpu,
    'mem': cmd_mem,
    'ps': cmd_ps,
    'man': cmd_man,
    'uptime': cmd_uptime,
}

# Routes

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route("/cwd", methods=["GET"])
def get_cwd():
    return jsonify(cwd=os.getcwd())


@app.route("/")
def index():
    return render_template("index.html")

# NLP parse route
@app.route("/parse_nlp", methods=["POST"])
def parse_nlp():
    data = request.json
    nl_command = data.get("command", "")
    parsed_command = ai_parse_command(nl_command)
    return jsonify(parsed=parsed_command)

# Run command route
@app.route("/run", methods=["POST"])
def run():
    data = request.json
    command_line = data.get("command", "")
    try:
        parts = shlex.split(command_line)
    except Exception as e:
        return jsonify(result=f"parse error: {e}")

    if not parts:
        return jsonify(result="")

    cmd = parts[0]
    args = parts[1:]

    if cmd in COMMANDS:
        result = COMMANDS[cmd](args)
    else:
        try:
            res = subprocess.run(command_line, shell=True, capture_output=True, text=True)
            result = res.stdout + res.stderr
        except Exception as e:
            result = f"Unknown command or error: {e}"

    return jsonify(result=result)

# File write route for cat > and cat >>
@app.route("/cat_write", methods=["POST"])
def write_file():
    data = request.json
    filename = data.get("filename")
    content = data.get("content", "")
    append = data.get("append", False)
    result = cat_write(filename, content, append)
    return jsonify(result=result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
