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

    svc_json = cfgp.get("google", "service_account_json", fallback=None)
    spreadsheet_name = cfgp.get("google", "spreadsheet_name", fallback=None)
    spreadsheet_id = cfgp.get("google", "spreadsheet_id", fallback=None)
    worksheet_name = args.sheet or cfgp.get("google", "worksheet_name", fallback=None)

    ch_col = cfgp.get("google", "character_col", fallback="A")
    uk_col = cfgp.get("google", "russian_col", fallback="B")
    en_col = cfgp.get("google", "english_col", fallback="C")
    sv_col = cfgp.get("google", "swedish_col", fallback="D")
    header_rows = cfgp.getint("google", "header_rows", fallback=1)

    context_window = cfgp.getint("translation", "context_window", fallback=4)
    max_glossary_terms = cfgp.getint("translation", "max_glossary_terms", fallback=40)
    episode_synopsis_path = cfgp.get("translation", "episode_synopsis", fallback="")
    preserve_cues = cfgp.getboolean("translation", "preserve_cues", fallback=True)
    approx_length_match = cfgp.getboolean("translation", "approx_length_match", fallback=True)
    default_limit = cfgp.getint("translation", "default_limit", fallback=0)

    api_key = cfgp.get("openai", "api_key", fallback=os.getenv("OPENAI_API_KEY"))
    model = cfgp.get("openai", "model", fallback="gpt-4o-mini")
    temperature = cfgp.getfloat("openai", "temperature", fallback=0.2)
    base_prompt_path = cfgp.get("openai", "base_prompt_path", fallback="prompts/base_prompt.txt")

    skip_translated = cfgp.getboolean("run", "skip_translated", fallback=True)
    dry_run_cfg = cfgp.getboolean("run", "dry_run", fallback=False)

    limit = args.limit if args.limit is not None else default_limit
    start_row = args.start_row if args.start_row is not None else (header_rows + 1)
    dry_run = args.dry_run or dry_run_cfg
    force = args.force

    if not api_key:
        print("OpenAI API key not provided (openai.api_key or OPENAI_API_KEY).", file=sys.stderr)
        sys.exit(2)

    base_prompt_default = read_file_or_default(base_prompt_path, "")
    episode_synopsis = read_file_or_default(episode_synopsis_path, "")

    translator = LineTranslator(TranslatorConfig(
        api_key=api_key, model=model, temperature=temperature,
        base_prompt=base_prompt_default, preserve_cues=preserve_cues,
        approx_length_match=approx_length_match
    ))
    rctx = RollingContext(window_size=context_window, max_glossary_terms=max_glossary_terms)

    client = SheetClient(svc_json, spreadsheet_name, spreadsheet_id)
    if worksheet_name is None or worksheet_name.strip() == "":
        worksheet_name = pick_sheet_interactively(client)
    ws = client.worksheet(worksheet_name)

    rows = client.read_rows(ws, start_row, ch_col, uk_col, en_col, sv_col, header_rows, limit=limit)
    logger.info("Processing %d row(s) in sheet '%s'", len(rows), worksheet_name)

    processed = 0
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

    logger.info("Done. Wrote %d new translation(s).", processed)

if __name__ == "__main__":
    main()
