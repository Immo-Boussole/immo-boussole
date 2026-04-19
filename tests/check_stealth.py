try:
    import playwright_stealth
    print(f"Names in playwright_stealth: {dir(playwright_stealth)}")
    from playwright_stealth import Stealth
    print("Stealth found")
    try:
        from playwright_stealth import stealth_async
        print("stealth_async found")
    except ImportError:
        print("stealth_async NOT found")
except ImportError:
    print("playwright_stealth NOT installed")
