# -*- coding: utf-8 -*-
import datetime
import re

from common import utils
from django.db import models
from django.conf import settings


class Company(models.Model):

    name = models.CharField(max_length=32, unique=True)
    car_wash_count = models.IntegerField(default=0)  # 旗下洗车行数量


class CarWash(models.Model):

    """
    @note: 洗车行
    """
    wash_type_choices = ((0, u'人工'), (1, u'机器'), (2, u''), )

    company = models.ForeignKey("Company", null=True)   # 洗车行对应的集团公司
    city_id = models.IntegerField(db_index=True)
    district_id = models.IntegerField(db_index=True)

    name = models.CharField(max_length=64, unique=True)
    business_hours = models.CharField(max_length=64)  # 营业时间
    tel = models.CharField(max_length=32)
    addr = models.CharField(max_length=256)
    longitude = models.CharField(max_length=32, null=True)  # 经度
    latitude = models.CharField(max_length=32, null=True)  # 纬度
    wash_type = models.IntegerField(default=0, db_index=True, choices=wash_type_choices)    # 洗车方式
    des = models.TextField(null=True)  # 简介
    note = models.TextField(null=True)   # 温馨提示，使用提醒
    lowest_sale_price = models.FloatField(db_index=True)  # 最低售价
    lowest_origin_price = models.FloatField()  # 最低原价
    imgs = models.TextField()  # 多张轮播图融为一个字段
    rating = models.IntegerField(default=0, db_index=True)  # 评分
    order_count = models.IntegerField(default=0, db_index=True)  # 订单数量

    valid_date_start = models.DateTimeField(null=True)  # 有效期开始时间
    valid_date_end = models.DateTimeField(null=True)  # 有效期结束时间
    is_vip = models.BooleanField(default=False)
    vip_info = models.CharField(max_length=64, null=True)

    sort_num = models.IntegerField(default=0, db_index=True)
    state = models.BooleanField(default=True, db_index=True)
    create_time = models.DateTimeField(auto_now_add=True)

    def __unicode__(self):
        return '%s, %s' % (self.id, self.name)

    def get_url(self):
        return "/car_wash/%s" % self.id

    def get_district(self):
        from www.city.interface import CityBase
        return CityBase().get_district_by_id(self.district_id)

    def get_price_minus(self):
        return self.lowest_origin_price - self.lowest_sale_price

    def get_cover(self):

        tag_img = re.compile('<img .*?src=[\"\'](.+?)[\"\']')
        imgs = tag_img.findall(self.imgs)
        if imgs:
            return imgs[0]
        return '%simg/default_car_wash_100.png' % settings.MEDIA_URL

    def get_imgs(self):
        tag_img = re.compile('<img .*?src=[\"\'](.+?)[\"\']')
        imgs = tag_img.findall(self.imgs)
        if not imgs:
            return ['%simg/default_car_wash_640.png' % settings.MEDIA_URL, ]
        return imgs

    def get_imgs_len(self):
        return self.get_imgs().__len__()


class CarWashBank(models.Model):

    """
    @note: 洗车行结算信息
    """
    car_wash = models.ForeignKey("CarWash")
    manager_name = models.CharField(max_length=16)
    mobile = models.CharField(max_length=16)
    tel = models.CharField(max_length=16)
    bank_name = models.CharField(max_length=16)
    bank_card = models.CharField(max_length=32)
    balance_date = models.DateField(null=True)  # 结算日期


group_choices = ((0, u'洗车专用'), (1, u''))


class ServiceType(models.Model):

    """
    @note: 服务类型
    """
    name = models.CharField(max_length=32, unique=True)
    group = models.IntegerField(default=0, db_index=True, choices=group_choices)  # 大类
    sort_num = models.IntegerField(default=0, db_index=True)
    state = models.BooleanField(default=True, db_index=True)


class ServicePrice(models.Model):

    """
    @note: 服务价格
    """
    car_wash = models.ForeignKey("CarWash")
    service_type = models.ForeignKey("ServiceType")

    sale_price = models.FloatField(db_index=True)  # 售价
    origin_price = models.FloatField(db_index=True)  # 原价
    clear_price = models.FloatField(db_index=True)  # 和厂商结算价
    sort_num = models.IntegerField(default=0, db_index=True)
    state = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["sort_num", "sale_price"]
        unique_together = [("car_wash", "service_type"), ]


class Coupon(models.Model):

    """
    @note: 优惠券
    """
    coupon_type_choices = ((0, u'优惠特定金额'), (1, u'优惠至特定金额'))
    platform_choices = ((0, u'无限制'), (1, u'微信端专用'))
    state_choices = ((0, u'未领取'), (1, u'正常'), (2, u'已使用'), (3, u'已过期'))

    code = models.CharField(max_length=64, unique=True)  # 优惠券编码
    coupon_type = models.IntegerField(default=1, choices=coupon_type_choices)
    discount = models.FloatField(db_index=True)  # 优惠幅度(小于1代表折扣率，大于1代表折扣金额)
    expiry_time = models.DateTimeField(db_index=True)  # 失效时间
    minimum_amount = models.FloatField(default=0)  # 最低消费额
    user_id = models.CharField(max_length=36, db_index=True, null=True)  # 用户
    car_wash = models.ForeignKey("CarWash", null=True)

    service_group = models.IntegerField(default=0, choices=group_choices)  # 使用类型
    platform = models.IntegerField(default=0, db_index=True, choices=platform_choices)  # 使用平台
    create_time = models.DateTimeField(auto_now_add=True)  # 创建时间
    state = models.IntegerField(default=1, db_index=True, choices=state_choices)
    email_flag = models.BooleanField(default=False)  # 标记是否发送过优惠卷过期提醒消息

    class Meta:
        ordering = ['state', "expiry_time"]

    def __unicode__(self):
        return str(self.code)

    def check_is_expiry(self):
        return self.expiry_time < datetime.datetime.now()

    def get_state_show(self):
        if self.state != 1:
            return self.get_state_display()

        if self.check_is_expiry():
            if self.state != 3:
                self.state = 3
                self.save()

        return self.get_state_display()

    def get_note(self):
        '''
        @note: 获取使用说明
        '''
        note = u'全场通用，无限制条件'
        if self.coupon_type == 0:
            note = u"凭此优惠券，下单时可立减现金%s元" % utils.smart_show_float(self.discount)
        elif self.coupon_type == 1:
            note = u"凭此优惠券，可享受%s元洗车" % utils.smart_show_float(self.discount)

        if self.minimum_amount > 0 and self.minimum_amount != self.discount:
            note += u' (最低消费%s元)' % utils.smart_show_float(self.minimum_amount)
        car_wash = self.car_wash
        if car_wash:
            note = u', 仅限洗车行<a href="%s">%s</a>使用' % (car_wash.get_url(), car_wash.name)
        return note
