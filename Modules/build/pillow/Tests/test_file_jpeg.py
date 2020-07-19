from helper import unittest, PillowTestCase, hopper, py3
from helper import djpeg_available, cjpeg_available

import random
from io import BytesIO
import os

from PIL import Image
from PIL import ImageFile
from PIL import JpegImagePlugin

codecs = dir(Image.core)

TEST_FILE = "Tests/images/hopper.jpg"


class TestFileJpeg(PillowTestCase):

    def setUp(self):
        if "jpeg_encoder" not in codecs or "jpeg_decoder" not in codecs:
            self.skipTest("jpeg support not available")

    def roundtrip(self, im, **options):
        out = BytesIO()
        im.save(out, "JPEG", **options)
        test_bytes = out.tell()
        out.seek(0)
        im = Image.open(out)
        im.bytes = test_bytes  # for testing only
        return im

    def test_sanity(self):

        # internal version number
        self.assertRegexpMatches(Image.core.jpeglib_version, "\d+\.\d+$")

        im = Image.open(TEST_FILE)
        im.load()
        self.assertEqual(im.mode, "RGB")
        self.assertEqual(im.size, (128, 128))
        self.assertEqual(im.format, "JPEG")

    def test_app(self):
        # Test APP/COM reader (@PIL135)
        im = Image.open(TEST_FILE)
        self.assertEqual(
            im.applist[0],
            ("APP0", b"JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"))
        self.assertEqual(im.applist[1], (
            "COM", b"File written by Adobe Photoshop\xa8 4.0\x00"))
        self.assertEqual(len(im.applist), 2)

    def test_cmyk(self):
        # Test CMYK handling.  Thanks to Tim and Charlie for test data,
        # Michael for getting me to look one more time.
        f = "Tests/images/pil_sample_cmyk.jpg"
        im = Image.open(f)
        # the source image has red pixels in the upper left corner.
        c, m, y, k = [x / 255.0 for x in im.getpixel((0, 0))]
        self.assertEqual(c, 0.0)
        self.assertGreater(m, 0.8)
        self.assertGreater(y, 0.8)
        self.assertEqual(k, 0.0)
        # the opposite corner is black
        c, m, y, k = [x / 255.0 for x in im.getpixel((
            im.size[0]-1, im.size[1]-1))]
        self.assertGreater(k, 0.9)
        # roundtrip, and check again
        im = self.roundtrip(im)
        c, m, y, k = [x / 255.0 for x in im.getpixel((0, 0))]
        self.assertEqual(c, 0.0)
        self.assertGreater(m, 0.8)
        self.assertGreater(y, 0.8)
        self.assertEqual(k, 0.0)
        c, m, y, k = [x / 255.0 for x in im.getpixel((
            im.size[0]-1, im.size[1]-1))]
        self.assertGreater(k, 0.9)

    def test_dpi(self):
        def test(xdpi, ydpi=None):
            im = Image.open(TEST_FILE)
            im = self.roundtrip(im, dpi=(xdpi, ydpi or xdpi))
            return im.info.get("dpi")
        self.assertEqual(test(72), (72, 72))
        self.assertEqual(test(300), (300, 300))
        self.assertEqual(test(100, 200), (100, 200))
        self.assertEqual(test(0), None)  # square pixels

    def test_icc(self):
        # Test ICC support
        im1 = Image.open("Tests/images/rgb.jpg")
        icc_profile = im1.info["icc_profile"]
        self.assertEqual(len(icc_profile), 3144)
        # Roundtrip via physical file.
        f = self.tempfile("temp.jpg")
        im1.save(f, icc_profile=icc_profile)
        im2 = Image.open(f)
        self.assertEqual(im2.info.get("icc_profile"), icc_profile)
        # Roundtrip via memory buffer.
        im1 = self.roundtrip(hopper())
        im2 = self.roundtrip(hopper(), icc_profile=icc_profile)
        self.assert_image_equal(im1, im2)
        self.assertFalse(im1.info.get("icc_profile"))
        self.assertTrue(im2.info.get("icc_profile"))

    def test_icc_big(self):
        # Make sure that the "extra" support handles large blocks
        def test(n):
            # The ICC APP marker can store 65519 bytes per marker, so
            # using a 4-byte test code should allow us to detect out of
            # order issues.
            icc_profile = (b"Test"*int(n/4+1))[:n]
            assert len(icc_profile) == n  # sanity
            im1 = self.roundtrip(hopper(), icc_profile=icc_profile)
            self.assertEqual(im1.info.get("icc_profile"), icc_profile or None)
        test(0)
        test(1)
        test(3)
        test(4)
        test(5)
        test(65533-14)  # full JPEG marker block
        test(65533-14+1)  # full block plus one byte
        test(ImageFile.MAXBLOCK)  # full buffer block
        test(ImageFile.MAXBLOCK+1)  # full buffer block plus one byte
        test(ImageFile.MAXBLOCK*4+3)  # large block

    def test_optimize(self):
        im1 = self.roundtrip(hopper())
        im2 = self.roundtrip(hopper(), optimize=1)
        self.assert_image_equal(im1, im2)
        self.assertGreaterEqual(im1.bytes, im2.bytes)

    def test_optimize_large_buffer(self):
        # https://github.com/python-pillow/Pillow/issues/148
        f = self.tempfile('temp.jpg')
        # this requires ~ 1.5x Image.MAXBLOCK
        im = Image.new("RGB", (4096, 4096), 0xff3333)
        im.save(f, format="JPEG", optimize=True)

    def test_progressive(self):
        im1 = self.roundtrip(hopper())
        im2 = self.roundtrip(hopper(), progressive=True)
        self.assert_image_equal(im1, im2)
        self.assertGreaterEqual(im1.bytes, im2.bytes)

    def test_progressive_large_buffer(self):
        f = self.tempfile('temp.jpg')
        # this requires ~ 1.5x Image.MAXBLOCK
        im = Image.new("RGB", (4096, 4096), 0xff3333)
        im.save(f, format="JPEG", progressive=True)

    def test_progressive_large_buffer_highest_quality(self):
        f = self.tempfile('temp.jpg')
        if py3:
            a = bytes(random.randint(0, 255) for _ in range(256 * 256 * 3))
        else:
            a = b''.join(chr(random.randint(0, 255)) for _ in range(
                256 * 256 * 3))
        im = Image.frombuffer("RGB", (256, 256), a, "raw", "RGB", 0, 1)
        # this requires more bytes than pixels in the image
        im.save(f, format="JPEG", progressive=True, quality=100)

    def test_large_exif(self):
        # https://github.com/python-pillow/Pillow/issues/148
        f = self.tempfile('temp.jpg')
        im = hopper()
        im.save(f, 'JPEG', quality=90, exif=b"1"*65532)

    def test_progressive_compat(self):
        im1 = self.roundtrip(hopper())
        im2 = self.roundtrip(hopper(), progressive=1)
        im3 = self.roundtrip(hopper(), progression=1)  # compatibility
        self.assert_image_equal(im1, im2)
        self.assert_image_equal(im1, im3)
        self.assertFalse(im1.info.get("progressive"))
        self.assertFalse(im1.info.get("progression"))
        self.assertTrue(im2.info.get("progressive"))
        self.assertTrue(im2.info.get("progression"))
        self.assertTrue(im3.info.get("progressive"))
        self.assertTrue(im3.info.get("progression"))

    def test_quality(self):
        im1 = self.roundtrip(hopper())
        im2 = self.roundtrip(hopper(), quality=50)
        self.assert_image(im1, im2.mode, im2.size)
        self.assertGreaterEqual(im1.bytes, im2.bytes)

    def test_smooth(self):
        im1 = self.roundtrip(hopper())
        im2 = self.roundtrip(hopper(), smooth=100)
        self.assert_image(im1, im2.mode, im2.size)

    def test_subsampling(self):
        def getsampling(im):
            layer = im.layer
            return layer[0][1:3] + layer[1][1:3] + layer[2][1:3]
        # experimental API
        im = self.roundtrip(hopper(), subsampling=-1)  # default
        self.assertEqual(getsampling(im), (2, 2, 1, 1, 1, 1))
        im = self.roundtrip(hopper(), subsampling=0)  # 4:4:4
        self.assertEqual(getsampling(im), (1, 1, 1, 1, 1, 1))
        im = self.roundtrip(hopper(), subsampling=1)  # 4:2:2
        self.assertEqual(getsampling(im), (2, 1, 1, 1, 1, 1))
        im = self.roundtrip(hopper(), subsampling=2)  # 4:1:1
        self.assertEqual(getsampling(im), (2, 2, 1, 1, 1, 1))
        im = self.roundtrip(hopper(), subsampling=3)  # default (undefined)
        self.assertEqual(getsampling(im), (2, 2, 1, 1, 1, 1))

        im = self.roundtrip(hopper(), subsampling="4:4:4")
        self.assertEqual(getsampling(im), (1, 1, 1, 1, 1, 1))
        im = self.roundtrip(hopper(), subsampling="4:2:2")
        self.assertEqual(getsampling(im), (2, 1, 1, 1, 1, 1))
        im = self.roundtrip(hopper(), subsampling="4:1:1")
        self.assertEqual(getsampling(im), (2, 2, 1, 1, 1, 1))

        self.assertRaises(
            TypeError, lambda: self.roundtrip(hopper(), subsampling="1:1:1"))

    def test_exif(self):
        im = Image.open("Tests/images/pil_sample_rgb.jpg")
        info = im._getexif()
        self.assertEqual(info[305], 'Adobe Photoshop CS Macintosh')

    def test_mp(self):
        im = Image.open("Tests/images/pil_sample_rgb.jpg")
        self.assertIsNone(im._getmp())

    def test_quality_keep(self):
        # RGB
        im = Image.open("Tests/images/hopper.jpg")
        f = self.tempfile('temp.jpg')
        im.save(f, quality='keep')
        # Grayscale
        im = Image.open("Tests/images/hopper_gray.jpg")
        f = self.tempfile('temp.jpg')
        im.save(f, quality='keep')
        # CMYK
        im = Image.open("Tests/images/pil_sample_cmyk.jpg")
        f = self.tempfile('temp.jpg')
        im.save(f, quality='keep')

    def test_junk_jpeg_header(self):
        # https://github.com/python-pillow/Pillow/issues/630
        filename = "Tests/images/junk_jpeg_header.jpg"
        Image.open(filename)

    def test_qtables(self):
        im = Image.open("Tests/images/hopper.jpg")
        qtables = im.quantization
        reloaded = self.roundtrip(im, qtables=qtables, subsampling=0)
        self.assertEqual(im.quantization, reloaded.quantization)
        self.assert_image_similar(im, self.roundtrip(im, qtables='web_low'),
                                  30)
        self.assert_image_similar(im, self.roundtrip(im, qtables='web_high'),
                                  30)
        self.assert_image_similar(im, self.roundtrip(im, qtables='keep'), 30)

        # values from wizard.txt in jpeg9-a src package.
        standard_l_qtable = [int(s) for s in """
            16  11  10  16  24  40  51  61
            12  12  14  19  26  58  60  55
            14  13  16  24  40  57  69  56
            14  17  22  29  51  87  80  62
            18  22  37  56  68 109 103  77
            24  35  55  64  81 104 113  92
            49  64  78  87 103 121 120 101
            72  92  95  98 112 100 103  99
            """.split(None)]

        standard_chrominance_qtable = [int(s) for s in """
            17  18  24  47  99  99  99  99
            18  21  26  66  99  99  99  99
            24  26  56  99  99  99  99  99
            47  66  99  99  99  99  99  99
            99  99  99  99  99  99  99  99
            99  99  99  99  99  99  99  99
            99  99  99  99  99  99  99  99
            99  99  99  99  99  99  99  99
            """.split(None)]
        # list of qtable lists
        self.assert_image_similar(
            im, self.roundtrip(
                im, qtables=[standard_l_qtable, standard_chrominance_qtable]),
            30)

        # tuple of qtable lists
        self.assert_image_similar(
            im, self.roundtrip(
                im, qtables=(standard_l_qtable, standard_chrominance_qtable)),
            30)

        # dict of qtable lists
        self.assert_image_similar(im,
                                  self.roundtrip(im,
                                                 qtables={0: standard_l_qtable,
                                                          1: standard_chrominance_qtable}),
                                  30)

        # not a sequence
        self.assertRaises(Exception, lambda: self.roundtrip(im, qtables='a'))
        # sequence wrong length
        self.assertRaises(Exception, lambda: self.roundtrip(im, qtables=[]))
        # sequence wrong length
        self.assertRaises(Exception, lambda: self.roundtrip(im, qtables=[1, 2, 3, 4, 5]))

        # qtable entry not a sequence
        self.assertRaises(Exception, lambda: self.roundtrip(im, qtables=[1]))
        # qtable entry has wrong number of items
        self.assertRaises(Exception, lambda: self.roundtrip(im, qtables=[[1, 2, 3, 4]]))

    @unittest.skipUnless(djpeg_available(), "djpeg not available")
    def test_load_djpeg(self):
        img = Image.open(TEST_FILE)
        img.load_djpeg()
        self.assert_image_similar(img, Image.open(TEST_FILE), 0)

    @unittest.skipUnless(cjpeg_available(), "cjpeg not available")
    def test_save_cjpeg(self):
        img = Image.open(TEST_FILE)

        tempfile = self.tempfile("temp.jpg")
        JpegImagePlugin._save_cjpeg(img, 0, tempfile)
        # Default save quality is 75%, so a tiny bit of difference is alright
        self.assert_image_similar(img, Image.open(tempfile), 17)

    def test_no_duplicate_0x1001_tag(self):
        # Arrange
        from PIL import ExifTags
        tag_ids = dict(zip(ExifTags.TAGS.values(), ExifTags.TAGS.keys()))

        # Assert
        self.assertEqual(tag_ids['RelatedImageWidth'], 0x1001)
        self.assertEqual(tag_ids['RelatedImageLength'], 0x1002)

    def test_MAXBLOCK_scaling(self):
        def gen_random_image(size):
            """ Generates a very hard to compress file
            :param size: tuple
            """
            return Image.frombytes('RGB', size, os.urandom(size[0]*size[1] * 3))

        im = gen_random_image((512, 512))
        f = self.tempfile("temp.jpeg")
        im.save(f, quality=100, optimize=True)

        reloaded = Image.open(f)

        # none of these should crash
        reloaded.save(f, quality='keep')
        reloaded.save(f, quality='keep', progressive=True)
        reloaded.save(f, quality='keep', optimize=True)


if __name__ == '__main__':
    unittest.main()

# End of file
