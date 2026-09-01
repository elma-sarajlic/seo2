# Assembly Maker daily SEO automation

This project now has a static-site version of the Arctos article workflow. It uses Gemini for text only, selects topics from `keywords.json`, reuses images that already belong to Assembly Maker, writes a standalone HTML article, updates the blog index and sitemap, saves the result to GitHub, and uploads the changed public files to cPanel over FTPS.

## What runs each day

The workflow `.github/workflows/daily-assemblymaker-blog.yml` runs once per day at 05:20 UTC. That is 07:20 in Sarajevo during daylight-saving time and 06:20 during standard time.

Each successful run:

1. Selects the next unused keyword and editorial angle.
2. Generates about 1,200 words with Gemini.
3. Applies content, link, HTML, FAQ, and minimum-length checks.
4. Reuses one image listed in `seo/image-library.json`; no image model is called.
5. Creates `blog/<article-slug>.html`.
6. Adds the article to `blog.html`, `blog/feed.json`, and `sitemap.xml`.
7. Commits those public changes to GitHub.
8. Uploads only the article, feed, blog index, and sitemap to cPanel.

The four keyword clusters, 60 supplied keywords, and six content angles provide up to 360 distinct keyword/angle slots. Add or replace keywords before that pool is exhausted, and remove weak phrases in `seo/config.json` under `excluded_keywords`.

## Upload to GitHub

Upload the Assembly Maker website source to the repository that should own this automation. The workflow expects these paths at the repository root:

```text
.github/workflows/daily-assemblymaker-blog.yml
seo/
tests/test_seo_generator.py
keywords.json
blog.html
sitemap.xml
site.css
assets/how-it-works-workshop.png
examples/agv.png
examples/arm.png
examples/drone.png
examples/mrp300.png
examples/nema17-pulley.png
examples/sg90-servo.png
```

It is simplest to upload the rest of the Assembly Maker website too, so GitHub is the complete source of the cPanel site. Do not upload any local `.env` file or API key.

In **GitHub → repository → Settings → Secrets and variables → Actions**, add these repository secrets:

```text
GEMINI_API_KEY       existing Gemini key; the same key may be reused
FTP_HOST             cPanel FTP/FTPS hostname
FTP_USERNAME         preferably a dedicated FTP account restricted to the site
FTP_PASSWORD         password for that FTP account
```

Optional repository variables:

```text
GEMINI_TEXT_MODEL=gemini-2.5-flash
FTP_REMOTE_ROOT=/assemblymaker.com
FTP_PORT=21
FTP_TLS=true
```

For this hosting layout, use `FTP_REMOTE_ROOT=/assemblymaker.com` when the FTP account opens in the parent directory and `assemblymaker.com` is visible there. If a dedicated FTP account opens directly inside the `assemblymaker.com` directory, use `FTP_REMOTE_ROOT=/`. Do not use `/public_html`, because that belongs to the other website.

Under **Settings → Actions → General → Workflow permissions**, allow read and write access so the bot can commit generated articles. A protected default branch must also allow GitHub Actions to push, or the history-commit step will need a separate automation branch.

## Upload to cPanel once

For the initial switch, upload these updated public files and folders into the `assemblymaker.com` document root:

```text
blog.html
sitemap.xml
site.css
site.js
assembly-maker-logo.png
logo_light.png
logo_dark.png
assets/how-it-works-workshop.png
examples/agv.png
examples/arm.png
examples/drone.png
examples/mrp300.png
examples/nema17-pulley.png
examples/sg90-servo.png
blog/                         if it already contains generated articles
```

The `hosting-upload` copies of `blog.html`, `sitemap.xml`, and `site.css` contain the same one-time public changes. Do **not** upload `.github/`, `seo/`, `keywords.json`, tests, the Gemini key, or FTP credentials to cPanel. Those are private build inputs and belong only in GitHub.

After the one-time upload, the workflow handles each daily article upload. You do not need to download a new ZIP or visit cPanel every day.

## First test

1. Push the files to GitHub.
2. Add the four required secrets.
3. Open **Actions → Daily Assembly Maker SEO Article → Run workflow**.
4. Leave the optional keyword blank for the normal rotation, or enter a one-off topic.
5. Confirm the run creates a commit and that `https://assemblymaker.com/blog.html` shows the new card.
6. Open the article and confirm the image, navigation, structured content, and mobile layout.

If the FTP step fails after generation, fix the FTP secret or remote root and rerun the same workflow that day. The generator detects that the day's article already exists and retries the saved deploy manifest rather than consuming a second keyword.

## Flutter app

No Flutter rebuild is required for this automatic static publishing design. The existing app is coupled to the Arctos WordPress approval API and can continue managing Arctos drafts. Assembly Maker articles publish through GitHub and cPanel, so pointing that app at this static site would require a new authenticated review API and would add a manual approval step to a workflow intended to publish daily.
