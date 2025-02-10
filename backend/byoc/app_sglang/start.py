from sglang.utils import (
    execute_shell_command,
    wait_for_server,
    terminate_process,
    print_highlight,
)
import argparse


if __file__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=str)
    parser.add_argument("--dtype",type=str,default="auto")
    parser.add_argument("--tp-size",type=int,default=1)
    args = parser.parse_args()

    print_highlight(f"Running with {args.model_path}")

    execute_shell_command(
        f"""
python3 -m sglang.launch_server --model-path {args.model_path} --tp-size {args.tp_size} --dtype {args.dtype} \
--port 8080 --host 0.0.0.0 --trust-remote-code
"""
    )

    wait_for_server("http://0.0.0.0:8080")

