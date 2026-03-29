from unittest.mock import MagicMock, patch

from realtime.watchlist import WatchlistManager

_VN30 = [
    "ACB",
    "BCM",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "POW",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
]


def test_load_from_env():
    mgr = WatchlistManager(watchlist_str="HPG,vcb, FPT ")
    symbols = mgr.get_symbols()
    assert symbols == ["FPT", "HPG", "VCB"]  # sorted, uppercased, stripped


def test_load_from_db_when_env_empty():
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = [("HPG",), ("VCB",)]

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    with patch("realtime.watchlist.engine", mock_engine):
        mgr = WatchlistManager(watchlist_str="")
        symbols = mgr.get_symbols()
    assert "HPG" in symbols
    assert "VCB" in symbols


def test_empty_env_falls_back_to_vn30_hardcode_on_db_error():
    with patch("realtime.watchlist.engine") as mock_engine:
        mock_engine.connect.side_effect = Exception("DB down")
        mgr = WatchlistManager(watchlist_str="")
        symbols = mgr.get_symbols()
    # Must return hardcoded VN30 fallback (30 symbols)
    assert len(symbols) == 30
    assert "HPG" in symbols


def test_no_duplicates():
    mgr = WatchlistManager(watchlist_str="HPG,HPG,VCB")
    assert mgr.get_symbols().count("HPG") == 1
