# Manual-image SEO workflow for Arctos and Assembly Maker

The daily generators now create text-only drafts. The Flutter app lists both websites, shows the article title, accepts an image selected from the phone, and publishes only after review. Flux is no longer used.

## Daily workflow

1. GitHub chooses a keyword and Gemini writes the article.
2. The article stays unpublished as a draft.
3. A webhook can send a phone notification with the article title.
4. Open **SEO Draft Review** and select **Arctos Robotics** or **Assembly Maker**.
5. Copy the title and use Gemini manually to create the image.
6. For Assembly Maker, tap **Add Image**, select the image, then tap **Publish**. Publishing is disabled until an image is uploaded.
7. For Arctos, open **Edit**, upload the replacement image, save, and publish as before.

The app checks both websites once when opened and every minute while it remains open. Closed-app phone notifications use the optional webhook described below.

## Assembly Maker: upload once to cPanel

The document root is the `assemblymaker.com` folder, not `public_html`.

Upload these files into `assemblymaker.com/api/`:

```text
api/seo-review.php
api/.htaccess
```

Make a copy of `api/seo-review-config.example.php`, name it `seo-review-config.php`, and upload it into the same `assemblymaker.com/api/` folder. In that private config:

- Set `review_token` to the same token used by the existing Arctos Flutter app.
- Keep `site_url` as `https://assemblymaker.com`.
- Keep `document_root` as `dirname(__DIR__)`.

Do not commit `seo-review-config.php` to GitHub. The supplied `.htaccess` blocks web access to both config filenames and the private draft data directory protects itself when first created.

The PHP/cPanel user must be able to write to:

```text
assemblymaker.com/blog/
assemblymaker.com/blog.html
assemblymaker.com/sitemap.xml
```

The API creates `assemblymaker.com/blog/images/` automatically when the first image is uploaded.

## Assembly Maker: upload to GitHub

Upload or replace:

```text
.github/workflows/daily-assemblymaker-blog.yml
seo/generate_article.py
seo/submit_draft.py
seo/requirements.txt
seo/article-template.html
seo/config.json
seo/image-library.json
seo/state.json
seo/draft-payload.json
tests/test_seo_generator.py
keywords.json
blog.html
blog/feed.json
sitemap.xml
site.css
```

In **GitHub → repository → Settings → Secrets and variables → Actions**, add:

```text
GEMINI_API_KEY       the existing Gemini key
REVIEW_API_TOKEN     exactly the same token used in the Flutter app and cPanel config
```

The previous FTP secrets can remain, but this workflow no longer uses FTP. It sends the draft to the protected cPanel review API; the API publishes the HTML only after the image is uploaded and **Publish** is tapped.

Optional repository variable:

```text
ASSEMBLY_REVIEW_API_URL=https://assemblymaker.com/api/seo-review.php?route=
```

The workflow already uses that URL by default, so the variable is normally unnecessary.

## Arctos: replace the workflow in its repository

Replace `.github/workflows/daily-seo-article.yml` in the Arctos SEO-generator repository with:

```text
arctos-manual-image/daily-seo-article.yml
```

This is the former Arctos workflow with Flux/Cloudflare image generation removed. It calls the existing bot with `--skip-image`, creates a WordPress draft, and retains the existing Flutter review API and optional notification webhook.

Cloudflare/Flux secrets are no longer required by this workflow. Leave them or remove them after the text-only run succeeds.

## Phone notifications

For notifications while the Flutter app is closed, one simple option is ntfy:

1. Install the **ntfy** app on the phone.
2. Choose a long, private topic name and subscribe to it in ntfy.
3. Its webhook URL will have the form `https://ntfy.sh/your-private-topic-name`.
4. Add that URL as the GitHub Actions repository secret `NOTIFICATION_WEBHOOK_URL` in both the Assembly Maker repository and the Arctos SEO-generator repository.

The Assembly notification says that a draft is ready and includes its title. A notification failure does not discard or publish the draft.

## Test order

1. Upload the cPanel API files and real config.
2. Upload the Assembly Maker GitHub changes and add `REVIEW_API_TOKEN`.
3. Install the rebuilt Flutter APK.
4. Run **Daily Assembly Maker SEO Article** manually in GitHub Actions.
5. Confirm the app shows the draft under **Assembly Maker**.
6. Copy the title, make the image in Gemini, tap **Add Image**, and select it.
7. Confirm that **Publish** becomes enabled, publish, and open the article URL.
8. Replace the Arctos workflow, run it manually, and confirm it creates a draft without a Flux image.

The Flutter app must be rebuilt and reinstalled once because it now knows about both APIs. Website changes after that do not require another app rebuild.
