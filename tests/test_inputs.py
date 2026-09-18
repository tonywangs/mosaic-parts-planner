import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from mosaic_parts.model import InputError, prepare_image, read_inventory, validate_grid


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "source.png"
        self.inventory = self.root / "inventory.json"

    def read(self, value):
        self.inventory.write_text(json.dumps(value), encoding="utf-8")
        return read_inventory(self.inventory)

    def test_valid_inventory(self):
        self.assertEqual(self.read({"colors": [{"name": "Blue", "rgb": [1, 2, 3], "available": 0}]})[0].rgb, (1, 2, 3))

    def test_invalid_inventory(self):
        valid = {"name": "Blue", "rgb": [1, 2, 3], "available": 3}
        bad_entries = [{**valid, "available": v} for v in (-1, 0.5, True, "3", None, 10**10)]
        bad_entries += [{**valid, "rgb": v} for v in ([1, 2], [1, 2, 256], [1, 2, -1], [True, 2, 3], "fff")]
        bad_entries += [{**valid, "name": v} for v in ("", " ", "a\nb", "a\x00b", " x", "x" * 81, None)]
        bad_entries += [{**valid, "typo": 1}, {"name": "x"}, []]
        for entry in bad_entries:
            with self.subTest(entry=entry), self.assertRaises(InputError):
                self.read({"colors": [entry]})
        for raw in ([], {}, {"colors": []}, {"colors": "x"}, {"colors": [valid] * 33},
                    {"colors": [valid, {**valid, "name": "blue"}]}, {"colors": [valid], "extra": 2}):
            with self.subTest(raw=raw), self.assertRaises(InputError):
                self.read(raw)

    def test_invalid_json_duplicate_keys_and_size(self):
        for text in ('{"colors":', '{"colors": [], "colors": []}', '{"colors":[{"name":"a","name":"b"}]}'):
            self.inventory.write_text(text)
            with self.assertRaises(InputError):
                read_inventory(self.inventory)
        self.inventory.write_bytes(b'\xff')
        with self.assertRaises(InputError):
            read_inventory(self.inventory)
        self.inventory.write_bytes(b' ' * (128 * 1024 + 1))
        with self.assertRaisesRegex(InputError, "exceeds"):
            read_inventory(self.inventory)

    def test_grid_limits(self):
        for w, h in ((0, 2), (-1, 1), (1, 129), (33, 32), (True, 2)):
            with self.subTest(size=(w, h)), self.assertRaises(InputError):
                validate_grid(w, h)
        validate_grid(32, 32)
        validate_grid(128, 8)

    def test_transparency_composited_before_resize(self):
        image = Image.new("RGBA", (2, 1))
        image.putdata([(255, 0, 0, 0), (0, 0, 255, 128)])
        image.save(self.image)
        target, _ = prepare_image(self.image, 2, 1, "stretch", (255, 255, 255))
        self.assertEqual(list(target.get_flattened_data()), [(255, 255, 255), (127, 127, 255)])

    def test_palette_transparency_and_grayscale(self):
        image = Image.new("P", (1, 1))
        image.putpalette([255, 0, 0] + [0] * 765)
        image.save(self.image, transparency=0)
        target, _ = prepare_image(self.image, 1, 1, "contain", (1, 2, 3))
        self.assertEqual(target.getpixel((0, 0)), (1, 2, 3))
        Image.new("L", (1, 1), 42).save(self.image)
        self.assertEqual(prepare_image(self.image, 1, 1, "cover", (0, 0, 0))[0].getpixel((0, 0)), (42, 42, 42))

    def test_fit_modes(self):
        Image.new("RGB", (4, 2), (255, 0, 0)).save(self.image)
        contained, _ = prepare_image(self.image, 4, 4, "contain", (1, 2, 3))
        self.assertEqual([contained.getpixel((0, y)) for y in range(4)],
                         [(1, 2, 3), (255, 0, 0), (255, 0, 0), (1, 2, 3)])
        for mode in ("cover", "stretch"):
            target, _ = prepare_image(self.image, 4, 4, mode, (1, 2, 3))
            self.assertEqual(set(target.get_flattened_data()), {(255, 0, 0)})
        # Center crop removes the outer columns without interpolation.
        image = Image.new("RGB", (4, 2))
        image.putdata([(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 0)] * 2)
        image.save(self.image)
        crop, _ = prepare_image(self.image, 2, 2, "cover", (0, 0, 0))
        self.assertEqual(list(crop.get_flattened_data()), [(255, 0, 0), (0, 255, 0)] * 2)

    def test_extreme_contain_aspect(self):
        Image.new("RGB", (8192, 1), "red").save(self.image)
        target, _ = prepare_image(self.image, 1, 128, "contain", (255, 255, 255))
        self.assertEqual(target.size, (1, 128))

    def test_all_exif_orientations(self):
        # Explicit expected front-view pixel matrices, independent of ImageOps.
        original = [1, 2, 3, 4, 5, 6]
        expected = {1: ((3, 2), [1, 2, 3, 4, 5, 6]), 2: ((3, 2), [3, 2, 1, 6, 5, 4]),
                    3: ((3, 2), [6, 5, 4, 3, 2, 1]), 4: ((3, 2), [4, 5, 6, 1, 2, 3]),
                    5: ((2, 3), [1, 4, 2, 5, 3, 6]), 6: ((2, 3), [4, 1, 5, 2, 6, 3]),
                    7: ((2, 3), [6, 3, 5, 2, 4, 1]), 8: ((2, 3), [3, 6, 2, 5, 1, 4])}
        for orientation, (size, pixels) in expected.items():
            image = Image.new("L", (3, 2))
            image.putdata(original)
            exif = Image.Exif(); exif[274] = orientation
            image.save(self.image, exif=exif)
            target, metadata = prepare_image(self.image, *size, "stretch", (255, 255, 255))
            self.assertEqual([p[0] for p in target.get_flattened_data()], pixels)
            self.assertEqual(metadata["oriented_size"], list(size))
            self.assertEqual(target.info, {})

    def test_jpeg_and_ignored_icc(self):
        image = Image.new("RGB", (3, 2), (20, 30, 40))
        exif = Image.Exif(); exif[274] = 6
        image.save(self.image, format="JPEG", exif=exif, icc_profile=b"test-profile")
        target, meta = prepare_image(self.image, 2, 3, "stretch", (255, 255, 255))
        self.assertEqual(meta["format"], "JPEG")
        self.assertEqual(meta["oriented_size"], [2, 3])
        self.assertTrue(meta["icc_profile_ignored"])
        self.assertEqual(target.info, {})

    def test_reject_formats_animation_modes_and_corruption(self):
        for mode, fmt in (("RGB", "GIF"), ("CMYK", "JPEG"), ("I;16", "PNG")):
            Image.new(mode, (2, 2)).save(self.image, format=fmt)
            with self.assertRaises(InputError):
                prepare_image(self.image, 2, 2, "contain", (0, 0, 0))
        Image.new("RGB", (2, 2), "red").save(self.image, save_all=True,
                                               append_images=[Image.new("RGB", (2, 2), "blue")])
        with self.assertRaisesRegex(InputError, "animated"):
            prepare_image(self.image, 2, 2, "contain", (0, 0, 0))
        for data in (b"not an image", b"\x89PNG\r\n\x1a\n", b""):
            self.image.write_bytes(data)
            with self.assertRaises(InputError):
                prepare_image(self.image, 2, 2, "contain", (0, 0, 0))

    def test_image_resource_limits(self):
        for size in ((8193, 1), (4001, 4000)):
            Image.new("L", size).save(self.image)
            with self.assertRaisesRegex(InputError, "exceeds"):
                prepare_image(self.image, 1, 1, "contain", (0, 0, 0))
        Image.new("RGB", (2, 2)).save(self.image)
        with patch("mosaic_parts.model.MAX_IMAGE_BYTES", 1), self.assertRaisesRegex(InputError, "exceeds"):
            prepare_image(self.image, 1, 1, "contain", (0, 0, 0))
