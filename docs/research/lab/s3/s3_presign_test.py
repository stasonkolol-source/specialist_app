"""S3 lab test: presigned PUT/GET/POST, signature/expiry enforcement, CORS, and imgproxy-from-S3.

Runs inside the compose network (service "s3test", python:3.13-slim + boto3). Lab-only credentials.
Writes a JSON report to /lab/results/s3_presign_results.json.
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.request
import uuid
import zlib

import boto3
from botocore.config import Config

TARGETS = [
    {"name": "garage v2.4.1", "endpoint": "http://garage:3900", "region": "garage", "bucket": "lab",
     "key": "GK0123456789abcdef0123456789abcd",
     "secret": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
    {"name": "seaweedfs 4.47", "endpoint": "http://seaweedfs:8333", "region": "us-east-1", "bucket": "lab",
     "key": "labaccesskey000000001", "secret": "labsecretkey00000000000000000000000000001"},
    {"name": "rustfs 1.0.0", "endpoint": "http://rustfs:9000", "region": "us-east-1", "bucket": "lab",
     "key": "labrustfsaccess", "secret": "labrustfssecret123456"},
]
IMGPROXY = {"url": "http://imgproxy:8080",
            "key": "943b421c9eb07c830af81030552c86009268de4e532ba2ee2eab8247c6da0881",
            "salt": "520f986b998545b4785e0defbc4f3c1203f22de2374a3d53cb7a7fe9fea309c5"}


def make_png(w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(v for x in range(w) for v in (x * 255 // w, y * 255 // h, 128)) for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def png_size(data: bytes):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def http(method, url, data=None, headers=None, timeout=15):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, dict(r.headers), body, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(), (time.perf_counter() - t0) * 1000
    except Exception as e:  # connection errors etc.
        return None, {}, str(e).encode(), (time.perf_counter() - t0) * 1000


def test_target(t, png):
    res = {"target": t["name"], "endpoint": t["endpoint"]}
    s3 = boto3.client("s3", endpoint_url=t["endpoint"], aws_access_key_id=t["key"], aws_secret_access_key=t["secret"],
                      region_name=t["region"], config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                                             retries={"max_attempts": 1}))
    b = t["bucket"]
    try:
        s3.create_bucket(Bucket=b)
        res["create_bucket"] = "created"
    except Exception as e:  # already exists (garage --default-bucket) or other
        res["create_bucket"] = f"{type(e).__name__}: {str(e)[:80]}"
    try:
        s3.head_bucket(Bucket=b)
        res["bucket_ok"] = True
    except Exception as e:
        res["bucket_ok"] = f"FAIL {str(e)[:80]}"
        return res
    # CORS
    try:
        s3.put_bucket_cors(Bucket=b, CORSConfiguration={"CORSRules": [{
            "AllowedMethods": ["GET", "PUT", "POST", "HEAD"], "AllowedOrigins": ["http://localhost:3000"],
            "AllowedHeaders": ["*"], "ExposeHeaders": ["ETag"], "MaxAgeSeconds": 600}]})
        rules = s3.get_bucket_cors(Bucket=b)["CORSRules"]
        res["put_get_bucket_cors"] = f"OK ({len(rules)} rule)"
    except Exception as e:
        res["put_get_bucket_cors"] = f"FAIL {type(e).__name__}: {str(e)[:100]}"
    key = f"uploads/{uuid.uuid4().hex}.png"
    # presigned PUT
    put_url = s3.generate_presigned_url("put_object", Params={"Bucket": b, "Key": key, "ContentType": "image/png"}, ExpiresIn=600)
    st, _, body, ms = http("PUT", put_url, data=png, headers={"Content-Type": "image/png"})
    res["presigned_put"] = f"{st} in {ms:.1f} ms" + ("" if st == 200 else f" {body[:120]!r}")
    # presigned GET + integrity
    get_url = s3.generate_presigned_url("get_object", Params={"Bucket": b, "Key": key}, ExpiresIn=600)
    st, hdr, body, ms = http("GET", get_url)
    res["presigned_get"] = f"{st} in {ms:.1f} ms, sha256 match={hashlib.sha256(body).hexdigest() == hashlib.sha256(png).hexdigest()}"
    try:
        res["head_content_type"] = s3.head_object(Bucket=b, Key=key)["ContentType"]
    except Exception as e:
        res["head_content_type"] = f"FAIL {str(e)[:80]}"
    # tampered signature must be rejected
    bad = get_url[:-4] + ("0000" if not get_url.endswith("0000") else "1111")
    st, _, _, _ = http("GET", bad)
    res["tampered_signature_rejected"] = f"{st == 403} (HTTP {st})"
    # expired URL must be rejected
    exp_url = s3.generate_presigned_url("get_object", Params={"Bucket": b, "Key": key}, ExpiresIn=1)
    time.sleep(2.5)
    st, _, body, _ = http("GET", exp_url)
    res["expired_url_rejected"] = f"{st in (400, 403)} (HTTP {st}{', ' + body[:160].decode(errors='replace') if st not in (200, 403) else ''})"
    # presigned POST (browser form upload with policy: content-type + size limit)
    try:
        post_key = f"uploads/{uuid.uuid4().hex}-post.png"
        post = s3.generate_presigned_post(b, post_key, Fields={"Content-Type": "image/png"},
                                          Conditions=[{"Content-Type": "image/png"}, ["content-length-range", 1, 5_000_000]],
                                          ExpiresIn=600)
        boundary = "----lab" + uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in post["fields"].items()]
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="post.png"\r\n'
                     f'Content-Type: image/png\r\n\r\n'.encode() + png + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        st, _, body, ms = http("POST", post["url"], data=b"".join(parts),
                               headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        ok = st in (200, 201, 204)
        stored = False
        if ok:
            try:
                stored = s3.head_object(Bucket=b, Key=post_key)["ContentLength"] == len(png)
            except Exception:
                stored = False
        res["presigned_post"] = f"HTTP {st}, stored={stored}" + ("" if ok else f" {body[:120]!r}")
    except Exception as e:
        res["presigned_post"] = f"FAIL {type(e).__name__}: {str(e)[:100]}"
    # CORS preflight
    obj_url = f"{t['endpoint']}/{b}/{key}"
    st, hdr, _, _ = http("OPTIONS", obj_url, headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT",
                                                      "Access-Control-Request-Headers": "content-type"})
    acao = {k.lower(): v for k, v in hdr.items()}.get("access-control-allow-origin")
    res["cors_preflight"] = f"HTTP {st}, Access-Control-Allow-Origin={acao}"
    res["_key"] = key
    return res


def imgproxy_test(key):
    k, s = bytes.fromhex(IMGPROXY["key"]), bytes.fromhex(IMGPROXY["salt"])
    out = {}
    for fmt in ("png", "webp"):
        path = f"/rs:fit:320:240/plain/s3://lab/{key}@{fmt}"
        sig = base64.urlsafe_b64encode(hmac.new(k, s + path.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        st, hdr, body, ms = http("GET", IMGPROXY["url"] + "/" + sig + path)
        info = {"status": st, "ms": round(ms, 1), "content_type": {k.lower(): v for k, v in hdr.items()}.get("content-type"),
                "bytes": len(body)}
        if fmt == "png":
            info["size"] = png_size(body)
        else:
            info["riff_webp"] = body[:4] == b"RIFF" and body[8:12] == b"WEBP"
        out[fmt] = info
    st, _, _, _ = http("GET", IMGPROXY["url"] + "/insecure/rs:fit:320:240/plain/s3://lab/" + key + "@png")
    out["unsigned_request_status"] = st
    return out


def main():
    png = make_png(640, 480)
    report = {"png_bytes": len(png), "targets": []}
    for t in TARGETS:
        try:
            r = test_target(t, png)
        except Exception as e:
            r = {"target": t["name"], "error": f"{type(e).__name__}: {str(e)[:200]}"}
        report["targets"].append(r)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    garage = next((r for r in report["targets"] if r["target"].startswith("garage") and "_key" in r), None)
    if garage:
        report["imgproxy_from_garage"] = imgproxy_test(garage["_key"])
        print(json.dumps(report["imgproxy_from_garage"], indent=1))
    with open("/lab/results/s3_presign_results.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
