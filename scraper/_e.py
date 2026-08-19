p = "scraper/rankings/usnews.py"
s = open(p, encoding="utf-8").read()
s = s.replace("limit=3000&from=2024&collapse=urlkey&filter=statuscode:200",
              "limit=3000&from=2022&collapse=urlkey&filter=statuscode:200")
open(p, "w", encoding="utf-8").write(s)
print("usnews CDX from=2022 ok")
