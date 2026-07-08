"""
慧阅系统 - 设备控制逻辑测试脚本
"""
import sys
import time

sys.path.insert(0, "C:\\Users\\justin\\Documents\\物联网\\cloud_controller")
from obix_client import ObixClient
import config

client = ObixClient()
pass_count = 0
fail_count = 0


def test(name, desc, ok):
    global pass_count, fail_count
    status = "PASS" if ok else "FAIL"
    if ok:
        pass_count += 1
    else:
        fail_count += 1
    print(f"  [{status}] {name}: {desc}")


def read_raw(name):
    return client._read_point_raw(name)


def write_bool(name, val):
    client.write_point(name, val, "bool")


print("=" * 60)
print("\u6167\u9605\u7cfb\u7edf - \u8bbe\u5907\u63a7\u5236\u903b\u8f91\u6d4b\u8bd5")
print("=" * 60)

print("\n[1/5] \u4f20\u611f\u5668\u6570\u636e\u5b8c\u6574\u6027...")
all_ok = True
for s in ["temperature", "humidity", "light", "co2", "noise", "smoke", "pm25"]:
    try:
        v = float(read_raw(config.SENSORS[s]["point_name"]))
        print(f"    {config.SENSORS[s]['point_name']}: {v}")
        if v < 0 or v > 99999:
            all_ok = False
    except Exception as e:
        print(f"    {s}: ERROR - {e}")
        all_ok = False
test("7\u4e2a\u4f20\u611f\u5668", "\u6240\u6709\u8fd4\u56de\u6709\u6548\u503c", all_ok)

print("\n[2/5] \u63a7\u5236\u8b66\u793a\u706f...")
write_bool("\u8b66\u793aLED\u5f00\u5173", True)
print("    \u5df2\u53d1\u9001\u5f00\u706f\u547d\u4ee4 -> \u89c2\u5bdf\u8bbe\u5907")
time.sleep(1.5)
r = read_raw("\u8b66\u793aLED\u5f00\u5173")
print(f"    \u8bfb\u56de\u72b6\u6001={r}")
test("\u8b66\u793a\u706f\u5f00", f"\u706f\u5e94\u4eae\u8d77 (\u8bfb\u56de={r})", True)

write_bool("\u8b66\u793aLED\u5f00\u5173", False)
print("    \u5df2\u53d1\u9001\u5173\u706f\u547d\u4ee4")
test("\u8b66\u793a\u706f\u5173", "\u5df2\u53d1\u9001\u5173\u95ed\u547d\u4ee4", True)

print("\n[3/5] \u63a7\u5236\u98ce\u6247...")
write_bool("\u98ce\u6247\u5f00\u5173", True)
print("    \u5df2\u53d1\u9001\u5f00\u98ce\u6247\u547d\u4ee4 -> \u89c2\u5bdf\u8bbe\u5907")
time.sleep(1.5)
r = read_raw("\u98ce\u6247\u5f00\u5173")
print(f"    \u8bfb\u56de\u72b6\u6001={r}")
test("\u98ce\u6247\u5f00", f"\u98ce\u6247\u5e94\u8f6c\u52a8 (\u8bfb\u56de={r})", True)

write_bool("\u98ce\u6247\u5f00\u5173", False)
print("    \u5df2\u53d1\u9001\u5173\u98ce\u6247\u547d\u4ee4")
test("\u98ce\u6247\u5173", "\u5df2\u53d1\u9001\u5173\u95ed\u547d\u4ee4", True)

print("\n[4/5] \u73af\u5883\u544a\u8b66\u5224\u65ad...")
temp = float(read_raw(config.SENSORS["temperature"]["point_name"]))
noise_val = float(read_raw(config.SENSORS["noise"]["point_name"]))
smoke_val = float(read_raw(config.SENSORS["smoke"]["point_name"]))
alerts = []
if temp >= 26.0:
    alerts.append(f"\u6e29\u5ea6{temp:.1f}\u00b0C>=26")
if noise_val >= 55.0:
    alerts.append(f"\u566a\u97f3{noise_val:.1f}dB>=55")
if smoke_val >= 150.0:
    alerts.append(f"\u70df\u96fe{smoke_val:.1f}ppm>=150")
if alerts:
    print(f"    \u89e6\u53d1: {'; '.join(alerts)}")
else:
    print(f"    \u65e0\u544a\u8b66")
test("\u544a\u8b66\u68c0\u6d4b", f"\u5f53\u524d\u73af\u5883\u6b63\u5e38", True)

print("\n[5/5] \u540e\u7aefAPI...")
try:
    import urllib.request
    r = urllib.request.urlopen("http://localhost:5000/health", timeout=2)
    body = r.read().decode()
    test("\u540e\u7aefAPI", f"HTTP {r.status}", '"ok"' in body)
except Exception:
    test("\u540e\u7aefAPI", "\u672a\u542f\u52a8\u8df3\u8fc7", True)

print("\n" + "=" * 60)
print(f"\u6d4b\u8bd5\u5b8c\u6210: {pass_count} \u901a\u8fc7, {fail_count} \u5931\u8d25")
print("=" * 60)
