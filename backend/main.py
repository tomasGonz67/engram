from fastapi import FastAPI

app = FastAPI()

@app.get("/helloworld")
def hello_world():
    return {"message": "Hello World"}
