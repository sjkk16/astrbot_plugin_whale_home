"""Regression checks for the independently generated preview, not project tests."""
import unittest
import numpy as np
from PIL import ImageFilter
import generate_idle as idle


class IdlePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.anim = idle.Animator()
        cls.original = np.array(cls.anim.original)

    def test_source_identity_and_size(self):
        self.assertEqual(idle.sha256(idle.SOURCE), idle.SOURCE_SHA256)
        self.assertEqual(self.anim.original.size, (500, 991))

    def test_eye_changes_stay_in_eye_region(self):
        for closure in (0, .15625, .5, .84375, 1):
            im = np.array(self.anim.blink(closure))
            diff = np.any(self.original != im, axis=-1)
            diff[109:154, 196:305] = False
            self.assertFalse(diff.any(), f'Unexpected face changes at {closure}')
            self.assertTrue(np.array_equal(self.original[..., 3], im[..., 3]))

    def test_breathing_does_not_move_head_or_feet(self):
        for breath in (0, .01, .5, 1):
            im = np.array(self.anim.warp(self.anim.original, breath))
            self.assertTrue(np.array_equal(self.original[:180], im[:180]))
            self.assertTrue(np.array_equal(self.original[660:], im[660:]))
            self.assertTrue(np.array_equal(self.original[:, :1], im[:, :1]))
            self.assertTrue(np.array_equal(self.original[:, -1:], im[:, -1:]))

    def test_breathing_creates_no_internal_transparency_holes(self):
        interior = np.array(self.anim.original.getchannel('A').filter(ImageFilter.MinFilter(7))) == 255
        for breath in (.01, .5, 1):
            im = np.array(self.anim.warp(self.anim.original, breath))
            self.assertTrue(np.all(im[..., 3][interior] == 255))

    def test_nearly_static_breath_has_no_brightness_step(self):
        a = idle.visible_pixels(self.original)
        b = idle.visible_pixels(np.array(self.anim.warp(self.anim.original, idle.breath_at(.05))))
        self.assertLess(float(np.abs(a-b).mean()), .015)

    def test_closed_lash_uses_selected_reference(self):
        from prepare_reference_lashes import LASHES
        from PIL import Image
        for eye, ref in zip(idle.EYES, LASHES):
            self.assertEqual(eye['closed'], ref['closed'])
            lash = np.array(Image.open(idle.HERE/'assets'/(eye['name']+'-reference-lash.png')))
            visible = lash[...,3] > 0
            self.assertTrue(visible.any())
            # Transferred pixels are ink, never a pink skin rectangle.
            self.assertLess(int(lash[visible,:3].max()), 90)

    def test_gif_light_background_stays_constant(self):
        from PIL import Image
        with Image.open(idle.HERE/'portrait-idle.gif') as im:
            self.assertEqual(im.convert('RGB').getpixel((0,0)), (238,242,242))
            im.seek(33)
            self.assertEqual(im.convert('RGB').getpixel((0,0)), (238,242,242))

    def test_two_blinks_and_periodic_endpoint(self):
        states = [idle.blink_at(i / idle.FPS) for i in range(idle.FRAMES)]
        starts = sum(states[i] > 0 and states[i-1] == 0 for i in range(1, len(states)))
        self.assertEqual(starts, 2)
        self.assertEqual(idle.blink_at(0), 0)
        self.assertEqual(idle.blink_at(6), 0)
        self.assertTrue(np.array_equal(np.array(self.anim.frame(0)), np.array(self.anim.frame(6))))


if __name__ == '__main__':
    unittest.main(verbosity=2)
