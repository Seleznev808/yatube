import shutil
import tempfile
from http import HTTPStatus

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..models import Comment, Follow, Group, Post

User = get_user_model()
TEMP_MEDIA_ROOT = tempfile.mkdtemp(dir=settings.BASE_DIR)


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class PostPagesTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = User.objects.create_user(username='author')
        cls.author_client = Client()
        cls.author_client.force_login(cls.author)
        cls.small_gif = (
            b'\x47\x49\x46\x38\x39\x61\x01\x00'
            b'\x01\x00\x00\x00\x00\x21\xf9\x04'
            b'\x01\x0a\x00\x01\x00\x2c\x00\x00'
            b'\x00\x00\x01\x00\x01\x00\x00\x02'
            b'\x02\x4c\x01\x00\x3b'
        )
        cls.uploaded = SimpleUploadedFile(
            name='small.gif',
            content=cls.small_gif,
            content_type='image/gif'
        )
        cls.group = Group.objects.create(
            title='Тестовая группа',
            slug='test-slug',
        )
        cls.post = Post.objects.create(
            author=cls.author,
            text='Тестовый пост',
            group=cls.group,
            image=cls.uploaded
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username='auth')
        self.authorized_client = Client()
        self.authorized_client.force_login(self.user)

    def assert_post_has_attribs(self, post):
        self.assertEqual(post.text, self.post.text)
        self.assertEqual(post.author, self.post.author)
        self.assertEqual(post.group, self.post.group)
        self.assertEqual(post.id, self.post.id)
        self.assertEqual(post.image, self.post.image)

    def test_pages_uses_correct_template(self):
        """URL-адрес использует соответствующий шаблон."""
        templates_page_names = {
            reverse('posts:index'): 'posts/index.html',
            reverse('posts:group_list', kwargs={'slug': self.group.slug}):
            'posts/group_list.html',
            reverse('posts:profile', kwargs={'username': self.post.author}):
            'posts/profile.html',
            reverse('posts:post_detail', kwargs={'post_id': self.post.id}):
            'posts/post_detail.html',
            reverse('posts:post_create'): 'posts/create_post.html',
            reverse('posts:post_edit', kwargs={'post_id': self.post.id}):
            'posts/create_post.html',
        }

        for reverse_name, template in templates_page_names.items():
            with self.subTest(template=template):
                response = self.author_client.get(reverse_name)
                self.assertTemplateUsed(response, template)

    def test_error_page(self):
        """Страница 404 использует кастомный шаблон."""
        response = self.client.get('/nonexist-page/')
        self.assertEqual(response.status_code, HTTPStatus.NOT_FOUND)
        self.assertTemplateUsed(response, 'core/404.html')

    def test_page_show_correct_context(self):
        """Шаблоны сформированы с правильным контекстом."""
        templates_page_names = {
            reverse('posts:index'): 'posts/index.html',
            reverse('posts:group_list', kwargs={'slug': self.group.slug}):
            'posts/group_list.html',
            reverse('posts:profile', kwargs={'username': self.post.author}):
            'posts/profile.html',
        }
        for reverse_name, template in templates_page_names.items():
            with self.subTest(template=template):
                response = self.author_client.get(reverse_name)
                post = response.context['page_obj'][0]
                self.assert_post_has_attribs(post)

    def test_post_detail_pages_show_correct_context(self):
        """Шаблон post_detail сформирован с правильным контекстом."""
        response = self.author_client.get(
            reverse('posts:post_detail', kwargs={'post_id': self.post.id})
        )
        post = response.context['post']
        self.assert_post_has_attribs(post)

    def test_create_show_correct_context(self):
        """Шаблоны create_post и post_edit
        сформированы с правильным контекстом.
        """
        templates_page_names = {
            reverse('posts:post_create'): 'posts/create_post.html',
            reverse('posts:post_edit', kwargs={'post_id': self.post.id}):
            'posts/create_post.html',
        }
        for reverse_name, template in templates_page_names.items():
            with self.subTest(template=template):
                response = self.author_client.get(reverse_name)
                form_fields = {
                    'text': forms.fields.CharField,
                    'group': forms.models.ChoiceField,
                }
                for value, expected in form_fields.items():
                    with self.subTest(value=value):
                        form_field = response.context['form'].fields[value]
                        self.assertIsInstance(form_field, expected)

    def test_check_group_in_pages(self):
        """Проверяем появление поста на необходимых страницах"""
        add_post = {
            reverse('posts:index'): Post.objects.get(group=self.post.group),
            reverse(
                'posts:group_list', kwargs={'slug': self.group.slug}
            ): Post.objects.get(group=self.post.group),
            reverse(
                'posts:profile', kwargs={'username': self.post.author}
            ): Post.objects.get(group=self.post.group),
        }
        for reverse_name, value in add_post.items():
            with self.subTest(reverse_name=reverse_name):
                response = self.author_client.get(reverse_name)
                form_field = response.context['page_obj']
                self.assertIn(value, form_field)

    def test_post_not_appear_in_else_group(self):
        """Проверяем, что пост не попал в группу,
        для которой не был предназначен.
        """
        post = Post.objects.exclude(group=self.post.group)
        response = self.author_client.get(
            reverse('posts:group_list', kwargs={'slug': self.group.slug})
        )
        form_field = response.context['page_obj']
        self.assertNotIn(post, form_field)

    def test_comment_appears_on_post_page(self):
        """Проверяем, что после успешной отправки комментарий
        появляется на странице поста."""
        comments_count = Comment.objects.count()
        form_data = {'text': 'Тестовый комментарий'}
        self.author_client.post(
            reverse('posts:add_comment', kwargs={'post_id': self.post.id}),
            data=form_data,
            follow=True,
        )
        self.assertEqual(Comment.objects.count(), comments_count + 1)
        self.assertTrue(
            Comment.objects.filter(text=form_data['text']).exists()
        )

    def test_anonymous_user_cannot_comment(self):
        """Проверка, что анонимный пользователь
        не может оставить комментарий.
        """
        comments_count = Comment.objects.count()
        form_data = {'text': 'Тестовый комментарий'}
        self.client.post(
            reverse('posts:add_comment', args=(self.post.id,)),
            data=form_data,
            follow=True,
        )
        self.assertEqual(Comment.objects.count(), comments_count)

    def test_checking_index_page_cache(self):
        """Проверка работы кэша главной страницы."""
        response = self.author_client.get(reverse('posts:index'))
        page_cach = response.content
        Post.objects.get(id=self.post.id).delete()
        response = self.author_client.get(reverse("posts:index"))
        self.assertEqual(response.content, page_cach)
        cache.clear()
        response = self.author_client.get(reverse('posts:index'))
        self.assertNotEqual(response.content, page_cach)

    def test_authorized_user_can_subscribe_to_other_users(self):
        """Авторизованный пользователь
        может подписываться на других пользователей.
        """
        follow_count = Follow.objects.count()
        self.authorized_client.get(
            reverse('posts:profile_follow', kwargs={'username': self.author})
        )
        self.assertTrue(
            Follow.objects.filter(user=self.user, author=self.author).exists()
        )
        self.assertEqual(Follow.objects.count(), follow_count + 1)

    def test_deleting_from_subscriptions(self):
        """Авторизованный пользователь
        может удалять пользователей из своих подписок.
        """
        Follow.objects.get_or_create(user=self.user, author=self.author)
        follow_count = Follow.objects.count()
        self.assertTrue(
            Follow.objects.filter(user=self.user, author=self.author).exists()
        )
        self.authorized_client.get(
            reverse('posts:profile_unfollow', kwargs={'username': self.author})
        )
        self.assertFalse(
            Follow.objects.filter(user=self.user, author=self.author).exists()
        )
        self.assertEqual(Follow.objects.count(), follow_count - 1)

    def test_appearance_of_post_among_subscribers(self):
        """Новая запись пользователя появляется в ленте тех,
        кто на него подписан.
        """
        Follow.objects.get_or_create(user=self.user, author=self.author)
        response = self.authorized_client.get(reverse('posts:follow_index'))
        self.assertIn(self.post, response.context['page_obj'])

    def test_post_not_appear_those_not_subscribed(self):
        """Новая запись пользователя не появляется в ленте тех,
        кто на него не подписан.
        """
        not_subscriber = User.objects.create_user(username='not_subscriber')
        self.authorized_client.force_login(not_subscriber)
        response = self.authorized_client.get(reverse('posts:follow_index'))
        self.assertNotIn(self.post, response.context['page_obj'])


class PaginatorViewsTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = User.objects.create_user(username='author')
        cls.author_client = Client()
        cls.author_client.force_login(cls.author)
        cls.group = Group.objects.create(
            title='Тестовая группа',
            slug='test-slug',
            description='Тестовое описание',
        )
        cls.posts = []
        for i in range(settings.NUMBER_OF_POSTS):
            cls.posts.append(Post(
                author=cls.author,
                text=f'Тестовый пост {i}',
                group=cls.group,
            ))
        Post.objects.bulk_create(cls.posts)
        cls.templates_page_names = {
            reverse('posts:index'): 'posts/index.html',
            reverse('posts:group_list', kwargs={'slug': cls.group.slug}):
            'posts/group_list.html',
            reverse('posts:profile', kwargs={'username': cls.author}):
            'posts/profile.html',
        }

    def test_pages_contains_required_number_records(self):
        """Проверяем количество постов на страницах"""
        for reverse_name, template in self.templates_page_names.items():
            with self.subTest(template=template):
                response = self.author_client.get(reverse_name)
                self.assertEqual(len(
                    response.context['page_obj']),
                    settings.NUMBER_OF_POSTS_ON_FIRST_PAGE
                )
                response = self.author_client.get(reverse_name + '?page=2')
                self.assertEqual(len(
                    response.context['page_obj']),
                    settings.NUMBER_OF_POSTS_ON_SECOND_PAGE
                )
