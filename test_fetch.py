import urllib.request
try:
    res = urllib.request.urlopen('http://localhost:8000/listings/164')
    print("Status:", res.getcode())
except Exception as e:
    print("Error:", e)
