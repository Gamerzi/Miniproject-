from playwright.sync_api import sync_playwright

# Separate profile just for this bot — keeps your real Chrome untouched
PROFILE_DIR = r"C:\Users\sasti\playwright_ig_profile"


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://www.instagram.com/")

        print("A browser window has opened.")
        print("Log in to Instagram manually in that window (handle 2FA if asked).")
        input("Once you're logged in and see your feed, press Enter here to save the session...")

        context.close()
        print(f"Session saved to: {PROFILE_DIR}")
        print("You can now run instagram_scraper.py — it will reuse this login.")


if __name__ == "__main__":
    main()