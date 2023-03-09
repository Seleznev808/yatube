from django.core.paginator import Paginator


def custom_paginator(request, post_list, number_pages):
    paginator = Paginator(post_list, number_pages)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return page_obj
