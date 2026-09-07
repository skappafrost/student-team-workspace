# AI-assist backend smoke output

register 201 {"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...","refresh_token":"...","token_type":"bearer","user":{"id":"...","name":"smoke1788406338","email":"smoke1788406338@example.com","role":"member"}}
me 200 {"id":"...","name":"smoke1788406338","email":"smoke1788406338@example.com","role":"member"}
workspace 201 {"id":"...","name":"Smoke WS","slug":"smoke-ws-1788406338","description":"x",...}
page 201 {"id":"...","title":"Smoke Page","slug":"smoke-page-1788406338","content":"This is a smoke test page about artificial intelligence.",...}
project 201 {"id":"...","name":"Smoke Project",...}
task 201 {"id":"...","title":"Smoke task","description":"This task is about machine learning and artificial intelligence.",...}
summarize task 200 {"summary":"Task: Smoke task. This task is about machine learning and artificial intelligence."}
summarize page 200 {"summary":"Page: Smoke Page. This is a smoke test page about artificial intelligence."}
search 200 {"results":[{"kind":"task",...,"score":3.5},{"kind":"page",...,"score":3.5}]}
