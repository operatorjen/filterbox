import os
import base64
import asyncio
import httpx
import random
from dotenv import load_dotenv
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from playwright.async_api import async_playwright

load_dotenv()

app = FastAPI()

PROVIDER = os.getenv("PROVIDER")
API_KEY = os.getenv("API_KEY")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")
TIMEZONE = os.getenv("TIMEZONE")
UA_CH_BRANDING = os.getenv("UA_CH_BRANDING")
UA_CH_MOBILE = os.getenv("UA_CH_MOBILE")
UA_CH_PLATFORM = os.getenv("UA_CH_PLATFORM")
WEBGL_VENDOR = os.getenv("WEBGL_VENDOR")
WEBGL_RENDERER = os.getenv("WEBGL_RENDERER")
USER_AGENT = os.getenv("USER_AGENT")
raw_args = os.getenv("ARGS")
ARGS = [arg.strip() for arg in raw_args.split("|")]

class Provider:
    @staticmethod
    async def analyze(content: str, prompt: str):
        configs = {
            "deepseek": {
                "url": "https://api.deepseek.com/chat/completions",
                "model": "deepseek-chat"
            },
            "openai": {
                "url": "https://api.openai.com/v1/chat/completions",
                "model": "gpt-4o"
            },
            "claude": {
                "url": "https://api.anthropic.com/v1/messages",
                "model": "claude-3-sonnet-20240229"
            },
            "ollama": {
                "url": f"{OLLAMA_HOST}/api/chat",
                "model": "llama3"
            }
        }
        
        config = configs.get(PROVIDER)
        if not config:
            return "ERROR | Unsupported Provider"

        async with httpx.AsyncClient() as client:
            try:
                if PROVIDER == "claude":
                    headers = {"x-api-key": API_KEY, "anthropic-version": "2023-06-01"}
                    payload = {"model": config["model"], "max_tokens": 1024, "messages": [{"role": "user", "content": f"{prompt}\n\n{content[:6000]}"}]}
                elif PROVIDER == "ollama":
                    headers = {}
                    payload = {"model": config["model"], "messages": [{"role": "user", "content": f"{prompt}\n\n{content[:6000]}"}], "stream": False}
                else:
                    headers = {"Authorization": f"Bearer {API_KEY}"}
                    payload = {"model": config["model"], "messages": [{"role": "system", "content": "Forensic analyst."}, {"role": "user", "content": f"{prompt}\n\n{content[:6000]}"}]}

                response = await client.post(config["url"], headers=headers, json=payload, timeout=30.0)
                data = response.json()

                if PROVIDER == "claude": return data["content"][0]["text"]
                if PROVIDER == "ollama": return data["message"]["content"]
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                return f"RED | ANALYSIS_ERROR: {str(e)}"

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html", "r") as f:
        return f.read()

@app.post("/screenshot")
async def get_screenshot(url: str = Form(...)):
    target_url = url.strip()
    if not (target_url.startswith("http://") or target_url.startswith("https://")):
        target_url = f"https://{target_url}"

    r_jitter = random.randint(-5, 5)
    g_jitter = random.randint(-5, 5)
    b_jitter = random.randint(-5, 5)

    v_width = 1280 + random.randint(-20, 20)
    v_height = 720 + random.randint(-20, 20)

    INIT_JS = f"""
    (() => {{
        const makeNative = (obj, prop) => {{
            const fn = obj[prop]
            fn.toString = () => `function ${{prop}}() {{ [native code] }}`
        }}
        const s = {{ r: {r_jitter}, g: {g_jitter}, b: {b_jitter} }}
        const ol = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function() {{
            const r = ol.apply(this, arguments)
            for (let i = 0; i < r.data.length; i += 4) {{ 
                r.data[i] += s.r; r.data[i+1] += s.g; r.data[i+2] += s.b
            }}
            return r
        }}
        makeNative(CanvasRenderingContext2D.prototype, 'getImageData');
        const getParam = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(param) {{
            if (param === 37445) return {WEBGL_VENDOR}
            if (param === 37446) return {WEBGL_RENDERER}
            return getParam.apply(this, arguments)
        }}
        makeNative(WebGLRenderingContext.prototype, 'getParameter');
        if (navigator.userAgentData) {{
            const brands = '{UA_CH_BRANDING}'.split(', ').map(b => {{
                const [n, v] = b.split(';v=')
                return {{ brand: n.replace(/\"/g, ''), version: v.replace(/\"/g, '') }}
            }})
            Object.defineProperty(navigator, 'userAgentData', {{
                get: () => ({{ brands, mobile: false, platform: '{UA_CH_PLATFORM}' }})
            }})
        }}
    }})()
    """

    script_tasks = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=ARGS
        )

        context = await browser.new_context(
            viewport={"width": v_width, "height": v_height},
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id=TIMEZONE,
            extra_http_headers={
                "sec-ch-ua": UA_CH_BRANDING,
                "sec-ch-ua-mobile": UA_CH_MOBILE,
                "sec-ch-ua-platform": UA_CH_PLATFORM
            }
        )

        await context.add_init_script(INIT_JS)
        page = await context.new_page()

        async def capture_script(res):
            try:
                await res.finished()
                text = await res.text()
                return {"url": res.url, "content": text, "size": len(text.encode('utf-8'))}
            except:
                return None

        page.on("response", lambda res: script_tasks.append(asyncio.create_task(capture_script(res))) 
                if any(ext in res.url.lower() for ext in ['.js', '.mjs', '.webgl', '.glsl', '.wgsl']) else None)

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except asyncio.TimeoutError:
                pass 

            await asyncio.sleep(5) 
            
            all_harvested = await asyncio.gather(*script_tasks)
            scripts = [s for s in all_harvested if s is not None]
            
            screenshot_bytes = await page.screenshot(type='jpeg', quality=70, full_page=True)
            b64_string = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            await browser.close()
            return JSONResponse(content={
                "success": True, 
                "image": f"data:image/jpeg;base64,{b64_string}", 
                "url": target_url, 
                "scripts": scripts
            })
            
        except Exception as e:
            await browser.close()
            return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

@app.post("/analyze")
async def analyze_script(script_content: str = Form(...)):
    prompt = (
        "Analyze the following code for a forensic systems review. "
        "Provide a 1-sentence summary of its function in as much detail as possible. "
        "Then, classify its 'Safety Zone': 'GREEN' (Safe), "
        "'YELLOW' (Tracking), or 'RED' (Malicious/Danger). "
        "Return the response in this exact format: [ZONE] | [summary]"
    )
    result = await Provider.analyze(script_content, prompt)
    return {"success": True, "analysis": result}