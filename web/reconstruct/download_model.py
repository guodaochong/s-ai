import requests, sys, os

files = [
    ("https://hf-mirror.com/stabilityai/TripoSR/resolve/main/model.ckpt",
     r"D:\jumpingbirds\S-AI\web\reconstruct\TripoSR\checkpoints\model.ckpt"),
]

for url, out in files:
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(f"Downloading {url} ...")
    r = requests.get(url, allow_redirects=True, stream=True, timeout=30)
    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    with open(out, "wb") as f:
        for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded * 100 // total
                print(f"  {pct}% ({downloaded // 1048576}MB / {total // 1048576}MB)")
            else:
                print(f"  {downloaded // 1048576}MB")
    print(f"Done: {downloaded // 1048576}MB")
