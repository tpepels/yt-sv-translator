import argparse, configparser, os, sys, logging
from .sheets import SheetClient
from .translator import LineTranslator, TranslatorConfig
from .context import RollingContext

def read_file_or_default(path, default_text):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return default_text

def build_cli():
    import argparse
    ap = argparse.ArgumentParser(description="YouTube bilingual script → Swedish translator")
    ap.add_argument("--config", default="config.ini", help="Path to config.ini")
    ap.add_argument("--sheet", default=None, help="Worksheet/tab name to process")
    ap.add_argument("--limit", type=int, default=None, help="Limit rows (0 = no limit)")
    ap.add_argument("--start-row", type=int, default=None, help="Start at row (1-based)")
    ap.add_argument("--force", action="store_true", help="Re-translate even if Swedish cell is non-empty")
    ap.add_argument("--dry-run", action="store_true", help="Do not write to Sheets")
    return ap

def pick_sheet_interactively(client: SheetClient):
    titles = client.list_worksheets()
    print("Available sheets:")
    for i, t in enumerate(titles, 1):
        print(f"  {i}. {t}")
    while True:
        sel = input("Pick a sheet by number: ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(titles):
            return titles[int(sel)-1]
        print("Invalid selection.")

import time, random

def is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    # Cover common Google Sheets quota signals
    return (
        "429" in msg or
        "quota exceeded" in msg or
        "ratelimit" in msg or
        "userRateLimitExceeded".lower() in msg or
        "rateLimitExceeded".lower() in msg
    )

def write_cell_with_retry(client, ws, row, col, value, *,
                          max_retries: int = 8,
                          base_delay: float = 1.0,
                          max_delay: float = 60.0,
                          logger=None) -> bool:
    """
    Try to write a single cell. On 429/quota errors, retry with exponential backoff + jitter.
    Returns True on success, False if all retries failed.
    """
    for attempt in range(max_retries):
        try:
            client.write_cell(ws, row, col, value)
            return True
        except Exception as e:
            if is_rate_limit_error(e):
                # Exponential backoff with jitter
                sleep_s = min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, 0.5)
                if logger:
                    logger.warning(
                        "Rate limited on write (row %s, col %s). Retry %d/%d in %.1fs. Error: %s",
                        row, col, attempt + 1, max_retries, sleep_s, e
                    )
                time.sleep(sleep_s)
                continue
            else:
                # Non-quota error → don't loop forever
                if logger:
                    logger.error("Row %s: write failed (non-quota): %s", row, e)
                return False
    if logger:
        logger.error("Row %s: write failed after %d retries due to quota.", row, max_retries)
    return False

def write_range_with_retry(client, ws, col_letter, start_row, values, *,
                           max_retries: int = 8,
                           base_delay: float = 1.0,
                           max_delay: float = 60.0,
                           logger=None) -> bool:
    for attempt in range(max_retries):
        try:
            client.write_col_range(ws, col_letter, start_row, values, user_entered=True)
            # after a successful range write
            time.sleep(0.2)
            return True
        except Exception as e:
            if is_rate_limit_error(e):
                sleep_s = min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, 0.5)
                if logger:
                    logger.warning(
                        "Rate limited on range write (%s%d:%s%d, %d cells). Retry %d/%d in %.1fs. Error: %s",
                        col_letter, start_row, col_letter, start_row + len(values) - 1,
                        len(values), attempt + 1, max_retries, sleep_s, e
                    )
                time.sleep(sleep_s)
                continue
            else:
                if logger:
                    logger.error("Range write failed (non-quota): %s", e)
                return False
    if logger:
        logger.error("Range write failed after %d retries due to quota.", max_retries)
    return False


def main():
    ap = build_cli()
    args = ap.parse_args()

    cfgp = configparser.ConfigParser()
    if not os.path.exists(args.config):
        print(f"Missing config file: {args.config}", file=sys.stderr)
        sys.exit(1)
    cfgp.read(args.config, encoding="utf-8")

    log_level = cfgp.get("logging", "level", fallback="INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format="%(levelname)s: %(message)s")
    logger = logging.getLogger("yt-sv-translator")

    # Google
    svc_json = cfgp.get("google", "service_account_json", fallback=None)
    spreadsheet_name = cfgp.get("google", "spreadsheet_name", fallback=None)
    spreadsheet_id = cfgp.get("google", "spreadsheet_id", fallback=None)
    worksheet_name = args.sheet or cfgp.get("google", "worksheet_name", fallback=None)

    # Columns (keeping your 'russian_col' naming for compatibility)
    ch_col = cfgp.get("google", "character_col", fallback="A")
    uk_col = cfgp.get("google", "russian_col", fallback="B")
    en_col = cfgp.get("google", "english_col", fallback="C")
    sv_col = cfgp.get("google", "swedish_col", fallback="D")
    header_rows = cfgp.getint("google", "header_rows", fallback=1)

    # Translation / context
    context_window = cfgp.getint("translation", "context_window", fallback=4)
    max_glossary_terms = cfgp.getint("translation", "max_glossary_terms", fallback=40)
    episode_synopsis_path = cfgp.get("translation", "episode_synopsis", fallback="")
    preserve_cues = cfgp.getboolean("translation", "preserve_cues", fallback=True)
    approx_length_match = cfgp.getboolean("translation", "approx_length_match", fallback=True)
    default_limit = cfgp.getint("translation", "default_limit", fallback=0)
    batch_size = cfgp.getint("translation", "batch_size", fallback=1)  # NEW

    # OpenAI
    api_key = cfgp.get("openai", "api_key", fallback=os.getenv("OPENAI_API_KEY"))
    model = cfgp.get("openai", "model", fallback="gpt-4o-mini")
    base_prompt_path = cfgp.get("openai", "base_prompt_path", fallback="prompts/base_prompt.txt")

    # Run flags
    skip_translated = cfgp.getboolean("run", "skip_translated", fallback=True)
    dry_run_cfg = cfgp.getboolean("run", "dry_run", fallback=False)

    # Merge CLI
    limit = args.limit if args.limit is not None else default_limit
    start_row = args.start_row if args.start_row is not None else (header_rows + 1)
    dry_run = args.dry_run or dry_run_cfg
    force = args.force

    if not api_key:
        print("OpenAI API key not provided (openai.api_key or OPENAI_API_KEY).", file=sys.stderr)
        sys.exit(2)

    # Compose prompts
    base_prompt_default = read_file_or_default(base_prompt_path, "")
    episode_synopsis = read_file_or_default(episode_synopsis_path, "")

    # Init translator + context
    translator = LineTranslator(TranslatorConfig(
        api_key=api_key, model=model,
        base_prompt=base_prompt_default, preserve_cues=preserve_cues,
        approx_length_match=approx_length_match
    ))
    rctx = RollingContext(window_size=context_window, max_glossary_terms=max_glossary_terms)

    # Sheets
    client = SheetClient(svc_json, spreadsheet_name, spreadsheet_id)
    if worksheet_name is None or worksheet_name.strip() == "":
        worksheet_name = pick_sheet_interactively(client)
    ws = client.worksheet(worksheet_name)

    rows = client.read_rows(ws, start_row, ch_col, uk_col, en_col, sv_col, header_rows, limit=limit)
    logger.info("Processing %d row(s) in sheet '%s'", len(rows), worksheet_name)

    processed = 0

    if batch_size <= 1:
        # ---------- Original per-line path (unchanged) ----------
        for r, ch, uk, en, sv in rows:
            if not (uk or en):
                continue

            if skip_translated and (not force) and sv.strip():
                rctx.update(ch, uk, en, sv)
                continue

            context_block = rctx.build_context_block()

            try:
                out_sv = translator.translate(ch, uk, en, context_block, episode_synopsis)
            except Exception as e:
                logger.error("Row %d: translation failed: %s", r, e)
                continue

            if dry_run:
                logger.info("[dry-run] Row %d (%s) → %s", r, ch, out_sv)
            else:
                try:
                    client.write_cell(ws, r, sv_col, out_sv)
                except Exception as e:
                    logger.error("Row %d: write failed: %s", r, e)
                    continue

            rctx.update(ch, uk, en, out_sv)
            processed += 1

    else:
        # ---------- NEW: batched path ----------
        pending = []  # list of (row_index, ch, uk, en)
        def flush_batch():
            nonlocal processed, pending
            if not pending:
                return
            # Build context once for the batch (cheap + fast)
            context_block = rctx.build_context_block()

            # Prepare items in the required shape
            items = [(ch, uk, en) for (_r, ch, uk, en) in pending]
            try:
                out_list = translator.translate_batch(items, context_block, episode_synopsis)
            except Exception as e:
                # On failure, fall back to single-line to salvage progress
                logger.warning("Batch failed (%d lines). Falling back to single-line. Error: %s", len(pending), e)
                for (_r, ch, uk, en) in pending:
                    try:
                        out_sv = translator.translate(ch, uk, en, context_block, episode_synopsis)
                    except Exception as e2:
                        logger.error("Row %d: translation failed: %s", _r, e2)
                        continue
                    if dry_run:
                        logger.info("[dry-run] Row %d (%s) → %s", _r, ch, out_sv)
                    else:
                        try:
                            ok = write_cell_with_retry(client, ws, _r, sv_col, out_sv, logger=logger)
                            if not ok:
                                continue
                        except Exception as e3:
                            logger.error("Row %d: write failed: %s", _r, e3)
                            continue
                    rctx.update(ch, uk, en, out_sv)
                    processed += 1
                pending = []
                return

            # Write results back in order
            # for (idx, (_r, ch, uk, en)) in enumerate(pending):
            #     out_sv = out_list[idx] if idx < len(out_list) else ""
            #     if dry_run:
            #         logger.info("[dry-run] Row %d (%s) → %s", _r, ch, out_sv)
            #     else:
            #         try:
            #             ok = write_cell_with_retry(client, ws, _r, sv_col, out_sv, logger=logger)
            #             if not ok:
            #                 continue
            #         except Exception as e:
            #             logger.error("Row %d: write failed: %s", _r, e)
            #             continue
            #     rctx.update(ch, uk, en, out_sv)
            #     processed += 1

            # pending = []

            # Write results back (single range write)
            first_row = pending[0][0]
            batch_values = [out_list[i] if i < len(out_list) else "" for i in range(len(pending))]

            if dry_run:
                for i, (_r, ch, uk, en) in enumerate(pending):
                    logger.info("[dry-run] Row %d (%s) → %s", _r, ch, batch_values[i])
                    rctx.update(ch, uk, en, batch_values[i])
                    processed += 1
            else:
                ok = write_range_with_retry(client, ws, sv_col, first_row, batch_values, logger=logger)
                if not ok:
                    logger.warning("Range write failed; falling back to per-cell writes.")
                    for i, (_r, ch, uk, en) in enumerate(pending):
                        v = batch_values[i]
                        if write_cell_with_retry(client, ws, _r, sv_col, v, logger=logger):
                            rctx.update(ch, uk, en, v)
                            processed += 1
                else:
                    for i, (_r, ch, uk, en) in enumerate(pending):
                        rctx.update(ch, uk, en, batch_values[i])
                        processed += 1

            pending = []



        for r, ch, uk, en, sv in rows:
            if not (uk or en):
                continue
            if skip_translated and (not force) and sv.strip():
                rctx.update(ch, uk, en, sv)
                continue

            pending.append((r, ch, uk, en))
            if len(pending) >= batch_size:
                flush_batch()

        # Flush any tail
        flush_batch()

    logger.info("Done. Wrote %d new translation(s).", processed)

if __name__ == "__main__":
    main()
