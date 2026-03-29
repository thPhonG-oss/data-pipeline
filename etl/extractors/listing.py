"""Extractor cho danh mục chứng khoán và phân ngành ICB."""

import json
from pathlib import Path

import pandas as pd
from vnstock_data import Listing

from etl.base.extractor import BaseExtractor
from utils.logger import logger
from utils.retry import vnstock_retry

# Đường dẫn mặc định tới file JSON ICB (relative to project root)
_DEFAULT_ICB_JSON = Path(__file__).parent.parent.parent / "docs" / "icb-industries.json"

# ── Bảng dịch tiếng Việt theo ICB id ─────────────────────────────────────────

_VI_LEVEL1: dict[int, str] = {
    10: "Công nghệ",
    15: "Viễn thông",
    20: "Y tế",
    30: "Tài chính",
    35: "Bất động sản",
    40: "Hàng tiêu dùng không thiết yếu",
    45: "Hàng tiêu dùng thiết yếu",
    50: "Công nghiệp",
    55: "Nguyên vật liệu cơ bản",
    60: "Năng lượng",
    65: "Dịch vụ tiện ích",
}

_VI_LEVEL2: dict[int, str] = {
    1010: "Công nghệ",
    1510: "Viễn thông",
    2010: "Y tế",
    3010: "Ngân hàng",
    3020: "Dịch vụ tài chính",
    3030: "Bảo hiểm",
    3510: "Bất động sản",
    4010: "Ô tô và Phụ tùng",
    4020: "Sản phẩm và Dịch vụ tiêu dùng",
    4030: "Truyền thông",
    4040: "Bán lẻ",
    4050: "Du lịch và Giải trí",
    4510: "Thực phẩm, Đồ uống và Thuốc lá",
    4520: "Chăm sóc cá nhân, Dược phẩm và Siêu thị",
    5010: "Xây dựng và Vật liệu",
    5020: "Hàng hóa và Dịch vụ công nghiệp",
    5510: "Tài nguyên cơ bản",
    5520: "Hóa chất",
    6010: "Năng lượng",
    6510: "Dịch vụ tiện ích",
}

_VI_LEVEL3: dict[int, str] = {
    101010: "Phần mềm và Dịch vụ máy tính",
    101020: "Phần cứng và Thiết bị công nghệ",
    151010: "Thiết bị viễn thông",
    151020: "Nhà cung cấp dịch vụ viễn thông",
    201010: "Cung cấp dịch vụ y tế",
    201020: "Thiết bị và Dịch vụ y tế",
    201030: "Dược phẩm và Công nghệ sinh học",
    301010: "Ngân hàng",
    302010: "Tài chính và Tín dụng",
    302020: "Ngân hàng đầu tư và Môi giới",
    302030: "Quỹ REIT thế chấp",
    302040: "Quỹ đầu tư đóng",
    302050: "Quỹ đầu tư mở và phương tiện đầu tư khác",
    303010: "Bảo hiểm nhân thọ",
    303020: "Bảo hiểm phi nhân thọ",
    351010: "Đầu tư và Phát triển dịch vụ bất động sản",
    351020: "Quỹ tín thác đầu tư bất động sản",
    401010: "Ô tô và Phụ tùng",
    402010: "Dịch vụ tiêu dùng",
    402020: "Hàng gia dụng và Xây dựng nhà ở",
    402030: "Hàng hóa giải trí",
    402040: "Hàng hóa cá nhân",
    403010: "Truyền thông",
    404010: "Bán lẻ",
    405010: "Du lịch và Giải trí",
    451010: "Đồ uống",
    451020: "Sản xuất thực phẩm",
    451030: "Thuốc lá",
    452010: "Chăm sóc cá nhân, Dược phẩm và Siêu thị",
    501010: "Xây dựng và Vật liệu",
    502010: "Hàng không vũ trụ và Quốc phòng",
    502020: "Thiết bị điện tử và điện",
    502030: "Công nghiệp tổng hợp",
    502040: "Kỹ thuật công nghiệp",
    502050: "Dịch vụ hỗ trợ công nghiệp",
    502060: "Vận tải công nghiệp",
    551010: "Nguyên liệu công nghiệp",
    551020: "Kim loại công nghiệp và Khai thác mỏ",
    551030: "Kim loại quý và Khai thác mỏ",
    552010: "Hóa chất",
    601010: "Dầu khí và Than đá",
    601020: "Năng lượng thay thế",
    651010: "Điện",
    651020: "Khí đốt, Nước và Đa tiện ích",
    651030: "Dịch vụ xử lý chất thải",
}

_VI_LEVEL4: dict[int, str] = {
    10101010: "Dịch vụ máy tính",
    10101015: "Phần mềm",
    10101020: "Dịch vụ kỹ thuật số tiêu dùng",
    10102010: "Chất bán dẫn",
    10102015: "Linh kiện điện tử",
    10102020: "Thiết bị công nghệ sản xuất",
    10102030: "Phần cứng máy tính",
    10102035: "Thiết bị văn phòng điện tử",
    15101010: "Thiết bị viễn thông",
    15102010: "Dịch vụ truyền hình cáp",
    15102015: "Dịch vụ viễn thông",
    20101010: "Cơ sở y tế",
    20101020: "Dịch vụ quản lý y tế",
    20101025: "Dịch vụ y tế",
    20101030: "Y tế: Khác",
    20102010: "Thiết bị y tế",
    20102015: "Vật tư y tế",
    20102020: "Dịch vụ xét nghiệm y tế",
    20103010: "Công nghệ sinh học",
    20103015: "Dược phẩm",
    20103020: "Sản xuất cần sa",
    30101010: "Ngân hàng",
    30201020: "Cho vay tiêu dùng",
    30201025: "Tài chính thế chấp",
    30201030: "Cung cấp dữ liệu tài chính",
    30202000: "Dịch vụ tài chính đa dạng",
    30202010: "Quản lý tài sản và Lưu ký",
    30202015: "Dịch vụ đầu tư và Môi giới",
    30203000: "REIT thế chấp: Đa dạng",
    30203010: "REIT thế chấp: Thương mại",
    30203020: "REIT thế chấp: Dân cư",
    30204000: "Quỹ đầu tư đóng",
    30205000: "Quỹ đầu tư mở và phương tiện đầu tư khác",
    30301010: "Bảo hiểm nhân thọ",
    30302010: "Bảo hiểm toàn diện",
    30302015: "Môi giới bảo hiểm",
    30302020: "Tái bảo hiểm",
    30302025: "Bảo hiểm tài sản và tai nạn",
    35101010: "Đầu tư và Phát triển bất động sản",
    35101015: "Dịch vụ bất động sản",
    35102000: "REIT đa dạng",
    35102010: "REIT y tế",
    35102015: "REIT khách sạn và lưu trú",
    35102020: "REIT công nghiệp",
    35102025: "REIT hạ tầng",
    35102030: "REIT văn phòng",
    35102040: "REIT nhà ở",
    35102045: "REIT bán lẻ",
    35102050: "REIT kho bãi",
    35102060: "REIT lâm nghiệp",
    35102070: "REIT chuyên biệt khác",
    40101010: "Dịch vụ ô tô",
    40101015: "Lốp xe",
    40101020: "Ô tô",
    40101025: "Phụ tùng ô tô",
    40201010: "Dịch vụ giáo dục",
    40201020: "Dịch vụ tang lễ và nghĩa địa",
    40201030: "Dịch vụ in ấn và sao chép",
    40201040: "Cho thuê và Thuê mướn",
    40201050: "Cơ sở lưu trữ",
    40201060: "Dịch vụ ẩm thực và bán hàng tự động",
    40201070: "Dịch vụ tiêu dùng: Khác",
    40202010: "Xây dựng nhà ở",
    40202015: "Nội thất gia đình",
    40202020: "Thiết bị gia dụng",
    40202025: "Sản phẩm và Thiết bị gia đình",
    40203010: "Điện tử tiêu dùng",
    40203040: "Giải trí điện tử",
    40203045: "Đồ chơi",
    40203050: "Sản phẩm giải trí",
    40203055: "Xe giải trí và Thuyền",
    40203060: "Nhiếp ảnh",
    40204020: "Quần áo và Phụ kiện",
    40204025: "Giày dép",
    40204030: "Hàng xa xỉ",
    40204035: "Mỹ phẩm",
    40301010: "Giải trí",
    40301020: "Đại lý truyền thông",
    40301030: "Xuất bản",
    40301035: "Phát thanh và Truyền hình",
    40401010: "Bán lẻ đa dạng",
    40401020: "Bán lẻ trang phục",
    40401025: "Bán lẻ vật liệu xây dựng và nội thất",
    40401030: "Bán lẻ chuyên ngành",
    40501010: "Hàng không",
    40501015: "Du lịch và Du ngoạn",
    40501020: "Sòng bạc và Cờ bạc",
    40501025: "Khách sạn và Nhà nghỉ",
    40501030: "Dịch vụ giải trí",
    40501040: "Nhà hàng và Quán bar",
    45101010: "Sản xuất bia",
    45101015: "Chưng cất rượu và Sản xuất vang",
    45101020: "Nước giải khát",
    45102010: "Nông nghiệp, Thủy sản, Chăn nuôi và Đồn điền",
    45102020: "Thực phẩm",
    45102030: "Chế biến trái cây và ngũ cốc",
    45102035: "Đường",
    45103010: "Thuốc lá",
    45201010: "Bán lẻ và Bán buôn thực phẩm",
    45201015: "Bán lẻ dược phẩm",
    45201020: "Sản phẩm chăm sóc cá nhân",
    45201030: "Sản phẩm gia dụng tiêu hao",
    45201040: "Hàng tiêu dùng thiết yếu khác",
    50101010: "Xây dựng",
    50101015: "Dịch vụ kỹ thuật và Hợp đồng",
    50101020: "Vật liệu xây dựng, Mái và Ống nước",
    50101025: "Hệ thống điều hòa không khí",
    50101030: "Xi măng",
    50101035: "Vật liệu xây dựng khác",
    50201010: "Hàng không vũ trụ",
    50201020: "Quốc phòng",
    50202010: "Linh kiện điện",
    50202020: "Thiết bị điện tử: Điều khiển và Lọc",
    50202025: "Thiết bị điện tử: Đồng hồ đo",
    50202030: "Thiết bị điện tử: Kiểm soát ô nhiễm",
    50202040: "Thiết bị điện tử: Khác",
    50203000: "Công nghiệp đa dạng",
    50203010: "Sơn và Lớp phủ",
    50203015: "Nhựa",
    50203020: "Kính",
    50203030: "Hộp đựng và Bao bì",
    50204000: "Máy móc: Công nghiệp",
    50204010: "Máy móc: Nông nghiệp",
    50204020: "Máy móc: Xây dựng và Vận chuyển",
    50204030: "Máy móc: Động cơ",
    50204040: "Máy móc: Công cụ",
    50204050: "Máy móc: Chuyên dụng",
    50205010: "Nhà cung cấp công nghiệp",
    50205015: "Dịch vụ xử lý giao dịch",
    50205020: "Dịch vụ hỗ trợ doanh nghiệp chuyên nghiệp",
    50205025: "Đào tạo và Tư vấn việc làm",
    50205030: "In ấn và Biểu mẫu kinh doanh",
    50205040: "Dịch vụ bảo vệ",
    50206010: "Vận tải đường bộ",
    50206015: "Xe thương mại và Phụ tùng",
    50206020: "Đường sắt",
    50206025: "Thiết bị đường sắt",
    50206030: "Vận tải đường thủy",
    50206040: "Dịch vụ giao hàng",
    50206050: "Cho thuê thiết bị và phương tiện thương mại",
    50206060: "Dịch vụ vận tải",
    55101000: "Nguyên liệu đa dạng",
    55101010: "Lâm nghiệp",
    55101015: "Giấy",
    55101020: "Sản phẩm dệt may",
    55102000: "Khai thác mỏ tổng hợp",
    55102010: "Sắt và Thép",
    55102015: "Gia công kim loại",
    55102035: "Nhôm",
    55102040: "Đồng",
    55102050: "Kim loại màu",
    55103020: "Kim cương và Đá quý",
    55103025: "Khai thác vàng",
    55103030: "Bạch kim và Kim loại quý",
    55201000: "Hóa chất: Đa dạng",
    55201010: "Hóa chất và Sợi tổng hợp",
    55201015: "Phân bón",
    55201020: "Hóa chất đặc biệt",
    60101000: "Dầu khí tích hợp",
    60101010: "Khai thác dầu thô",
    60101015: "Khoan dầu ngoài khơi và Dịch vụ khác",
    60101020: "Lọc dầu và Tiếp thị",
    60101030: "Thiết bị và Dịch vụ dầu khí",
    60101035: "Đường ống dẫn dầu khí",
    60101040: "Than đá",
    60102010: "Nhiên liệu thay thế",
    60102020: "Thiết bị năng lượng tái tạo",
    65101010: "Điện từ năng lượng tái tạo",
    65101015: "Điện từ năng lượng truyền thống",
    65102000: "Đa tiện ích",
    65102020: "Phân phối khí đốt",
    65102030: "Nước sạch",
    65103035: "Dịch vụ xử lý chất thải",
}

# all_symbols() từ vci chỉ trả về 2 cột (symbol, organ_name).
# Nguồn vnd trả về đầy đủ: exchange, type, status, listed_date, ...
_SYMBOLS_SOURCE = "vnd"


class ListingExtractor(BaseExtractor):
    """
    Lấy dữ liệu danh mục từ vnstock_data.Listing.

    - extract_symbols()    → DataFrame thô cho companies    (dùng vnd)
    - extract_industries() → DataFrame thô cho icb_industries (dùng self.source)
    """

    def extract(self, symbol: str = "", **kwargs) -> pd.DataFrame:
        """Alias cho extract_symbols() — tương thích BaseExtractor interface."""
        return self.extract_symbols()

    @vnstock_retry()
    def extract_symbols(self) -> pd.DataFrame:
        """Lấy toàn bộ mã chứng khoán từ Listing.all_symbols().

        Dùng nguồn vnd vì vci chỉ trả về 2 cột (symbol, organ_name).
        """
        logger.info(f"[listing] Listing({_SYMBOLS_SOURCE}).all_symbols()...")
        df = Listing(source=_SYMBOLS_SOURCE).all_symbols()
        if df is None or df.empty:
            raise ValueError("all_symbols() trả về DataFrame rỗng.")
        logger.info(f"[listing] Lấy được {len(df)} mã chứng khoán.")
        return df

    @vnstock_retry()
    def extract_industries(self) -> pd.DataFrame:
        """Lấy phân ngành ICB từ Listing.industries_icb()."""
        logger.info(f"[listing] Listing({self.source}).industries_icb()...")
        df = Listing(source=self.source).industries_icb()
        if df is None or df.empty:
            raise ValueError("industries_icb() trả về DataFrame rỗng.")
        logger.info(f"[listing] Lấy được {len(df)} ngành ICB.")
        return df

    def load_icb_from_json(self, json_path: Path | None = None) -> list[dict]:
        """
        Đọc file JSON ICB cục bộ và trả về danh sách record phẳng (flat list).

        Cấu trúc JSON: industries → supersectors → sectors → subsectors (4 cấp).

        Mỗi record có:
            icb_code    : str(id)
            en_icb_name : tên tiếng Anh từ JSON
            icb_name    : tên tiếng Việt (từ bảng dịch nội bộ)
            level       : 1, 2, 3, hoặc 4
            parent_code : str(id của node cha) hoặc None cho level 1
            definition  : chuỗi định nghĩa (chỉ có ở level 4), None cho các cấp khác

        Args:
            json_path: Đường dẫn tới file JSON. Mặc định: docs/icb-industries.json
                       tính từ thư mục gốc dự án.

        Returns:
            list[dict] — danh sách record sẵn sàng để transform.
        """
        path = Path(json_path) if json_path else _DEFAULT_ICB_JSON
        logger.info(f"[listing] Đọc ICB từ file JSON: {path}")

        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        records: list[dict] = []

        for industry in data.get("industries", []):
            ind_id = industry["id"]
            records.append(
                {
                    "icb_code": str(ind_id),
                    "en_icb_name": industry["name"],
                    "icb_name": _VI_LEVEL1.get(ind_id, industry["name"]),
                    "level": 1,
                    "parent_code": None,
                    "definition": None,
                }
            )

            for supersector in industry.get("supersectors", []):
                ss_id = supersector["id"]
                records.append(
                    {
                        "icb_code": str(ss_id),
                        "en_icb_name": supersector["name"],
                        "icb_name": _VI_LEVEL2.get(ss_id, supersector["name"]),
                        "level": 2,
                        "parent_code": str(ind_id),
                        "definition": None,
                    }
                )

                for sector in supersector.get("sectors", []):
                    sec_id = sector["id"]
                    records.append(
                        {
                            "icb_code": str(sec_id),
                            "en_icb_name": sector["name"],
                            "icb_name": _VI_LEVEL3.get(sec_id, sector["name"]),
                            "level": 3,
                            "parent_code": str(ss_id),
                            "definition": None,
                        }
                    )

                    for subsector in sector.get("subsectors", []):
                        sub_id = subsector["id"]
                        records.append(
                            {
                                "icb_code": str(sub_id),
                                "en_icb_name": subsector["name"],
                                "icb_name": _VI_LEVEL4.get(sub_id, subsector["name"]),
                                "level": 4,
                                "parent_code": str(sec_id),
                                "definition": subsector.get("definition"),
                            }
                        )

        logger.info(f"[listing] Đọc được {len(records)} node ICB từ file JSON.")
        return records
