from preprocess import Preprocessor
import subprocess

if __name__ == "__main__":
    pr = Preprocessor(repo_root="/Users/skpulipaka/Desktop/MyProjects/blog")
    diff_text = subprocess.check_output(["git", "diff", "HEAD~1", "HEAD"]).decode(
        "utf-8"
    )
    chunks = pr.run(diff_text)
    print(chunks[0])
