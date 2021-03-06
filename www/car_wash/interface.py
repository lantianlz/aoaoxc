# -*- coding: utf-8 -*-

import datetime
import random
from django.db import transaction
from django.conf import settings
from decimal import Decimal

from common import utils, debug, raw_sql
from www.misc import consts
from www.tasks import async_send_email
from www.account.interface import UserBase
from www.car_wash.models import CarWash, ServicePrice, ServiceType, CarWashBank
from www.car_wash.models import Coupon, Order, OrderCode, CarWashManager, Company, CompanyManager

dict_err = {
    20100: u'服务类型名称重复',
    20101: u'服务类型不存在或者已删除',
    20102: u'洗车行名称重复',
    20103: u'洗车行不存在或者已删除',
    20104: u'该洗车行已添加此服务类型',
    20105: u'该服务价格不存在或者已删除',
    20106: u'该洗车行已添加此服务价格',
    20107: u'该洗车行银行信息已存在',
    20108: u'该洗车行银行信息不存在或者已删除',
    20109: u'该洗车行价格已经产生订单，无法删除',

    20201: u'优惠券不存在',
    20202: u'不是你的优惠券不要用',
    20203: u'优惠券已过期',
    20204: u'优惠券只针对特定洗车行',
    20205: u'优惠券金额大于单次购买金额',
    20206: u'未满足最低使用金额要求',
    20210: u'小概率事件发生，优惠券编码重复，请重新添加',

    20301: u'订单不存在',
    20302: u'付款金额和订单金额不符，支付失败，请联系嗷嗷洗车客服人员！',
    20303: u'该支付对应的订单状态无效',
    20304: u'前后端总金额不一致，请重新下单',
    20305: u'洗车码不存在',
    20306: u'洗车码已使用或退款，无法验证',
    20307: u'订单状态异常，无法申请退款',
    20308: u'该订单已有洗车码被使用，无法退款',

    20401: u'该管理员已存在，请勿重复添加',
    20402: u'I get you，没权限的你怎么进来的',

    20501: u'该公司已存在，请勿重复添加',
    20502: u'没有找到对应的公司',
}
dict_err.update(consts.G_DICT_ERROR)

DEFAULT_DB = 'default'


def car_wash_required(func):
    def _decorator(self, car_wash, *args, **kwargs):
        car_wash = car_wash
        if not isinstance(car_wash, CarWash):
            car_wash = CarWashBase().get_car_wash_by_id(car_wash, state=None)
            if not car_wash:
                return 20103, dict_err.get(20103)
        return func(self, car_wash, *args, **kwargs)
    return _decorator


def service_type_required(func):
    def _decorator(self, service_type, *args, **kwargs):
        service_type = service_type
        if not isinstance(service_type, ServiceType):
            try:
                service_type = ServiceTypeBase().get_service_type_by_id(service_type)
            except ServiceType.DoesNotExist:
                return 20101, dict_err.get(20101)
        return func(self, service_type, *args, **kwargs)
    return _decorator


class CarWashBase(object):

    def format_car_washs_for_ajax(self, objs):
        datas = []
        for obj in objs:
            datas.append(dict(id=obj.id, url=obj.get_url(), name=obj.name, cover=obj.get_cover(),
                              district=obj.get_district().district, wash_type=obj.get_wash_type_display(),
                              lowest_sale_price=obj.lowest_sale_price, lowest_origin_price=obj.lowest_origin_price,
                              price_minus=str(obj.get_price_minus())
                              ))
        return datas

    def get_car_wash_by_id(self, id, state=True):
        try:
            ps = dict(id=id)
            if state is not None:
                ps.update(state=state)
            return CarWash.objects.get(**ps)
        except CarWash.DoesNotExist:
            return ""

    def validate_car_wash_info(city_id, district_id, name, business_hours, tel, addr, lowest_sale_price, lowest_origin_price, imgs):
        assert all((city_id, district_id, name, business_hours, tel, addr))
        lowest_sale_price = float(lowest_sale_price)
        lowest_origin_price = float(lowest_origin_price)
        assert lowest_sale_price >= 0 and lowest_origin_price >= 0
        assert lowest_sale_price <= lowest_origin_price

    def add_car_wash(self, city_id, district_id, name, business_hours, tel, addr,
                     lowest_sale_price, lowest_origin_price, longitude, latitude, imgs, cover,
                     wash_type=0, des=None, note=None, sort_num=0, state=True, company_id=None):
        try:
            self.validate_car_wash_info(district_id, name, business_hours, tel, addr, lowest_sale_price, lowest_origin_price, imgs)
        except:
            return 99801, dict_err.get(99801)
        if CarWash.objects.filter(name=name):
            return 20102, dict_err.get(20102)

        ps = dict(city_id=city_id, district_id=district_id, name=name, business_hours=business_hours, tel=tel, addr=addr, des=des,
                  lowest_sale_price=lowest_sale_price, lowest_origin_price=lowest_origin_price, longitude=longitude, latitude=latitude, imgs=imgs,
                  cover=cover, wash_type=wash_type, note=note, sort_num=sort_num, company_id=company_id, state=state)

        try:
            car_wash = CarWash.objects.create(**ps)

            # 更新公司洗车行数量
            if company_id:
                CompanyBase().update_company_count(company_id)

        except Exception, e:
            debug.get_debug_detail(e)
            return 99900, dict_err.get(99900)
        return 0, car_wash

    def get_car_washs_by_city_id(self, city_id, order_by_value="0"):
        dict_order_by = {"0": "id", "1": "lowest_sale_price", "2": "-order_count"}
        order_by_field = dict_order_by.get(order_by_value)
        return CarWash.objects.filter(city_id=city_id, state=True).order_by("-sort_num", order_by_field)

    def search_car_washs_for_admin(self, name="", state=True):
        return CarWash.objects.filter(name__contains=name, state=state)

    def modify_car_wash(self, car_wash_id, city_id, district_id, name, business_hours, tel, addr,
                        lowest_sale_price, lowest_origin_price, longitude, latitude, imgs, cover,
                        wash_type=0, des=None, note=None, sort_num=0, state=True, company_id=None):
        if not car_wash_id:
            return 99800, dict_err.get(99800)

        obj = self.get_car_wash_by_id(car_wash_id, None)
        if not obj:
            return 20103, dict_err.get(20103)

        try:
            self.validate_car_wash_info(district_id, name, business_hours, tel, addr, lowest_sale_price, lowest_origin_price, imgs)
        except:
            return 99801, dict_err.get(99801)

        temp = CarWash.objects.filter(name=name)
        if temp and temp[0].id != obj.id:
            return 20102, dict_err.get(20102)

        ps = dict(city_id=city_id, district_id=district_id, name=name, business_hours=business_hours, tel=tel, addr=addr, des=des,
                  lowest_sale_price=lowest_sale_price, lowest_origin_price=lowest_origin_price, longitude=longitude, latitude=latitude, imgs=imgs,
                  cover=cover, wash_type=wash_type, note=note, sort_num=sort_num, state=state, company_id=company_id)

        old_company_id = obj.company.id if obj.company else None

        for k, v in ps.items():
            setattr(obj, k, v)

        try:
            obj.save()

            # 修改老公司的洗车行数量
            if old_company_id:
                CompanyBase().update_company_count(old_company_id)

            # 修改新公司的洗车行数量
            if company_id:
                CompanyBase().update_company_count(company_id)

        except Exception, e:
            debug.get_debug_detail(e)
            return 99900, dict_err.get(99900)

        return 0, dict_err.get(0)

    def get_car_washs_by_name(self, name="", state=True):
        objs = CarWash.objects.all()

        if state is not None:
            objs = objs.filter(state=state)

        if name:
            objs = objs.filter(name__contains=name)

        return objs[:10]

    def get_car_wash_by_name(self, name="", state=True):
        objs = CarWash.objects.all()

        if state is not None:
            objs = objs.filter(state=state)

        if name:
            objs = objs.filter(name=name)

        return objs

    def get_car_wash_by_company_id(self, company_id, name=''):
        objs = CarWash.objects.filter(state=True, company__id=company_id)

        if name:
            objs = objs.filter(name__contains=name)

        return objs


class ServicePriceBase(object):

    @car_wash_required
    def add_service_price(self, car_wash_obj_or_id, service_type_id, sale_price, origin_price, clear_price, sort_num=0):
        try:
            sale_price = float(sale_price)
            origin_price = float(origin_price)
            clear_price = float(clear_price)
            assert sale_price <= origin_price
        except:
            return 99801, dict_err.get(99801)

        if not isinstance(car_wash_obj_or_id, CarWash):
            car_wash = self.get_car_wash_by_id(car_wash_obj_or_id)
        else:
            car_wash = car_wash_obj_or_id

        service_type = ServiceTypeBase().get_service_type_by_id(service_type_id)
        if not service_type:
            return 20101, dict_err.get(20101)
        if ServicePrice.objects.filter(car_wash=car_wash, service_type=service_type):
            return 20104, dict_err.get(20104)

        ps = dict(car_wash=car_wash, service_type=service_type, sale_price=sale_price,
                  origin_price=origin_price, clear_price=clear_price, sort_num=sort_num)
        sp = ServicePrice.objects.create(**ps)

        return 0, sp

    def get_service_prices_by_car_wash(self, car_wash, state=True):
        ps = dict(car_wash=car_wash)
        if state is not None:
            ps.update(state=state)
        return ServicePrice.objects.select_related("service_type").filter(**ps)

    def search_prices_for_admin(self, car_wash_name, state=True):
        objs = ServicePrice.objects.filter(state=state)

        if car_wash_name:
            car_wash = CarWashBase().get_car_wash_by_name(car_wash_name)

            objs = objs.filter(car_wash=car_wash)

        return objs

    def get_service_price_by_id(self, price_id, state=True):
        objs = ServicePrice.objects.select_related("car_wash", "service_type").filter(pk=price_id)
        if state != None:
            objs = objs.filter(state=state)

        return objs[0] if objs else None

    def modify_service_price(self, price_id, car_wash_id, service_type_id, sale_price, origin_price, clear_price, sort_num=0, state=True):
        try:
            sale_price = float(sale_price)
            origin_price = float(origin_price)
            clear_price = float(clear_price)
            assert sale_price <= origin_price
        except:
            return 99801, dict_err.get(99801)

        obj = self.get_service_price_by_id(price_id, None)
        if not obj:
            return 20105, dict_err.get(20105)

        car_wash = CarWashBase().get_car_wash_by_id(car_wash_id)
        if not car_wash:
            return 20103, dict_err.get(20103)

        service_type = ServiceTypeBase().get_service_type_by_id(service_type_id)
        if not service_type:
            return 20101, dict_err.get(20101)

        temp = ServicePrice.objects.filter(car_wash=car_wash, service_type=service_type)

        if temp and temp[0] != obj:
            return 20106, dict_err.get(20106)

        ps = dict(car_wash=car_wash, service_type=service_type, sale_price=sale_price,
                  origin_price=origin_price, clear_price=clear_price, sort_num=sort_num, state=state)

        for k, v in ps.items():
            setattr(obj, k, v)

        try:
            obj.save()
        except:
            return 99900, dict_err.get(99900)

        return 0, dict_err.get(0)

    def remove_service_price(self, price_id):
        if not price_id:
            return 99800, dict_err.get(99800)

        if Order.objects.filter(service_price__id=price_id).count() > 0:
            return 20109, dict_err.get(20109)

        try:
            ServicePrice.objects.get(id=price_id).delete()
        except Exception:
            return 99900, dict_err.get(99900)

        return 0, dict_err.get(0)


class ServiceTypeBase(object):

    def get_service_type_by_id(self, id, state=True):
        try:
            ps = dict(id=id)
            if state is not None:
                ps.update(state=state)
            return ServiceType.objects.get(**ps)
        except ServiceType.DoesNotExist:
            return ""

    def add_service_type(self, name, sort_num=0):
        if not name:
            return 99800, dict_err.get(99800)
        if ServiceType.objects.filter(name=name):
            return 20100, dict_err.get(20100)

        st = ServiceType.objects.create(name=name, sort_num=sort_num)
        return 0, st

    def modify_service_type(self, service_type_id, name, sort_num=0, state=True):
        if not name:
            return 99800, dict_err.get(99800)

        st = self.get_service_type_by_id(service_type_id, state=None)
        if not st:
            return 20101, dict_err.get(20101)

        if st.name != name and ServiceType.objects.filter(name=name):
            return 20100, dict_err.get(20100)

        st.name = name
        st.sort_num = sort_num
        st.state = state
        st.save()
        return 0, st

    def search_types_for_admin(self):
        return ServiceType.objects.all()

    def get_all_types(self, state=True):
        objs = ServiceType.objects.all()

        if state:
            objs.filter(state=state)

        return objs


class CarWashBankBase(object):

    def get_bank_by_car_wash(self, car_wash_id):
        return CarWashBank.objects.filter(car_wash__id=car_wash_id)

    def add_bank(self, car_wash_id, manager_name, mobile, tel, bank_name, bank_card, balance_date):
        if not (car_wash_id and manager_name and mobile
                and tel and bank_name and bank_card and balance_date):
            return 99800, dict_err.get(99800)

        if self.get_bank_by_car_wash(car_wash_id):
            return 20107, dict_err.get(20107)

        ps = dict(
            car_wash_id=car_wash_id,
            manager_name=manager_name,
            mobile=mobile,
            tel=tel,
            bank_name=bank_name,
            bank_card=bank_card,
            balance_date=balance_date
        )

        try:
            obj = CarWashBank.objects.create(**ps)
            return 0, obj
        except Exception, e:
            debug.get_debug_detail(e)
            return 99900, dict_err.get(99900)

    def search_banks_for_admin(self, car_wash_name):
        objs = CarWashBank.objects.select_related('car_wash').all()

        if car_wash_name:
            objs = objs.filter(car_wash__name__contains=car_wash_name)

        return objs

    def get_bank_by_id(self, bank_id, state=True):
        objs = CarWashBank.objects.filter(pk=bank_id)
        if state:
            objs.filter(state=state)
        return objs[0] if objs else None

    def modify_bank(self, bank_id, car_wash_id, manager_name, mobile, tel, bank_name, bank_card, balance_date):
        if not (bank_id, car_wash_id and manager_name and mobile
                and tel and bank_name and bank_card and balance_date):
            return 99800, dict_err.get(99800)

        obj = self.get_bank_by_id(bank_id, None)
        if not obj:
            return 20108, dict_err.get(20108)

        temp = self.get_bank_by_car_wash(car_wash_id)
        if temp and temp[0] != obj:
            return 20107, dict_err.get(20107)

        ps = dict(
            car_wash_id=car_wash_id,
            manager_name=manager_name,
            mobile=mobile,
            tel=tel,
            bank_name=bank_name,
            bank_card=bank_card,
            balance_date=balance_date
        )

        for k, v in ps.items():
            setattr(obj, k, v)

        try:
            obj.save()
        except:
            return 99900, dict_err.get(99900)

        return 0, dict_err.get(0)


class CarWashManagerBase(object):

    def get_cwm_by_user_id(self, user_id):
        """
        @note: 获取用户管理的第一个洗车行，用于自动跳转到管理的洗车行
        """
        cwms = list(CarWashManager.objects.select_related("car_wash").filter(user_id=user_id))
        if cwms:
            return cwms[0]

    def get_cwm_by_car_wash_and_user_id(self, car_wash_id, user_id):
        """
        @note: 获取用户管理的单个洗车行
        """
        cwms = list(CarWashManager.objects.select_related("car_wash").filter(car_wash=car_wash_id, user_id=user_id))
        if cwms:
            return cwms[0]

    def check_user_is_cwm(self, car_wash, user):
        """
        @note: 判断用户是否是某个洗车行管理员
        """
        if isinstance(user, (str, unicode)):
            user = UserBase().get_user_by_id(user)

        if not isinstance(car_wash, CarWash):
            car_wash = CarWashBase().get_car_wash_by_id(car_wash)

        # 公司管理员可以查看所有旗下洗车行数据
        if car_wash.company_id and CompanyManagerBase().check_user_is_cm(car_wash.company_id, user):
            return True
        cwm = self.get_cwm_by_car_wash_and_user_id(car_wash, user.id)
        return True if (cwm or user.is_staff()) else False

    @car_wash_required
    def add_car_wash_manager(self, car_wash, user_id):
        if user_id and not UserBase().get_user_login_by_id(user_id):
            return 99600, dict_err.get(99600)

        if CarWashManager.objects.filter(user_id=user_id, car_wash=car_wash):
            return 20401, dict_err.get(20401)

        cwm = CarWashManager.objects.create(user_id=user_id, car_wash=car_wash)
        return 0, cwm

    def search_managers_for_admin(self, car_wash_name):
        objs = CarWashManager.objects.select_related("car_wash").all()

        if car_wash_name:
            objs = objs.filter(car_wash__name__contains=car_wash_name)

        return objs

    def get_manager_by_id(self, manager_id):
        try:
            return CarWashManager.objects.select_related("car_wash").get(id=manager_id)
        except CarWashManager.DoesNotExist:
            pass

    @car_wash_required
    def modify_car_wash_manager(self, car_wash_obj_or_id, user_id):
        if user_id and not UserBase().get_user_login_by_id(user_id):
            return 99600, dict_err.get(99600)

        if not isinstance(car_wash_obj_or_id, CarWash):
            car_wash = self.get_car_wash_by_id(car_wash_obj_or_id)
        else:
            car_wash = car_wash_obj_or_id

        if CarWashManager.objects.filter(user_id=user_id, car_wash=car_wash):
            return 20401, dict_err.get(20401)

        cwm = CarWashManager.objects.create(user_id=user_id, car_wash=car_wash)
        return 0, cwm

    def delete_car_wash_manager(self, manager_id):
        if not manager_id:
            return 99800, dict_err.get(99800)

        try:
            CarWashManager.objects.get(id=manager_id).delete()
        except Exception:
            return 99900, dict_err.get(99900)

        return 0, dict_err.get(0)

# ===================================================订单和优惠券部分=================================================================#


def order_required(func):
    def _decorator(self, order, *args, **kwargs):
        order = order
        if not isinstance(order, Order):
            order = OrderBase().get_order_by_trade_id(order) or OrderBase().get_order_by_id(order)
            if not order:
                return 20301, dict_err.get(20301)
        return func(self, order, *args, **kwargs)
    return _decorator


class CouponBase(object):

    def get_coupon_by_id(self, id, user_id=None, state=1):
        try:
            ps = dict(id=id)
            if user_id is not None:
                ps.update(user_id=user_id)
            if state is not None:
                ps.update(state=state)
            return Coupon.objects.get(**ps)
        except Coupon.DoesNotExist:
            return ""

    def add_coupon(self, coupon_type, discount, expiry_time, user_id=None, minimum_amount=0, car_wash_id=None):
        try:
            discount = float(discount)
            minimum_amount = float(minimum_amount)

            assert discount >= 0 and minimum_amount >= 0 and expiry_time > datetime.datetime.now()
            if minimum_amount > 0:
                assert minimum_amount > discount
        except:
            return 99801, dict_err.get(99801)

        if user_id and not UserBase().get_user_login_by_id(user_id):
            return 99600, dict_err.get(99600)

        car_wash = None
        if car_wash_id:
            car_wash = CarWashBase().get_car_wash_by_id(car_wash_id)
            if not car_wash:
                return 20103, dict_err.get(20103)

        code = utils.get_radmon_int(length=12)
        if Coupon.objects.filter(code=code):
            return 20210, dict_err.get(20210)

        ps = dict(code=code, coupon_type=coupon_type, discount=discount, expiry_time=expiry_time,
                  user_id=user_id, minimum_amount=minimum_amount, car_wash=car_wash)

        try:
            coupon = Coupon.objects.create(**ps)
        except:
            return 99900, dict_err.get(99900)

        return 0, coupon

    def get_coupons_by_user_id(self, user_id):
        return Coupon.objects.filter(user_id=user_id)

    def get_valid_coupon_by_user_id(self, user_id):
        """
        @note: 获取有效的coupon用于前端使用
        """
        coupons = Coupon.objects.filter(user_id=user_id, state=1)
        datas = []
        for coupon in coupons:
            if not coupon.check_is_expiry():
                datas.append(coupon)
        return datas

    def search_coupons_for_admin(self, car_wash_name, nick, state=None):

        objs = Coupon.objects.all()

        if state is not None:
            objs = objs.filter(state=state)

        if car_wash_name:
            objs = objs.select_related('car_wash').filter(car_wash__name__contains=car_wash_name)
        elif nick:
            user = UserBase().get_user_by_nick(nick)
            if user:
                objs = objs.filter(user_id=user.id)
            else:
                objs = []

        return objs

    def modify_coupon(self, coupon_id, coupon_type, discount, expiry_time, user_id=None, minimum_amount=0, car_wash_id=None, state=1):
        try:
            discount = float(discount)
            minimum_amount = float(minimum_amount)

            assert discount >= 0 and minimum_amount >= 0 and expiry_time > datetime.datetime.now()
            if minimum_amount > 0:
                assert minimum_amount > discount
        except:
            return 99801, dict_err.get(99801)

        if user_id and not UserBase().get_user_login_by_id(user_id):
            return 99600, dict_err.get(99600)

        car_wash = None
        if car_wash_id:
            car_wash = CarWashBase().get_car_wash_by_id(car_wash_id)
            if not car_wash:
                return 20103, dict_err.get(20103)

        obj = self.get_coupon_by_id(coupon_id, None, None)
        if not obj:
            return 20201, dict_err.get(20201)

        ps = dict(coupon_type=coupon_type, discount=discount, expiry_time=expiry_time,
                  user_id=user_id, minimum_amount=minimum_amount, car_wash=car_wash, state=state)

        for k, v in ps.items():
            setattr(obj, k, v)

        try:
            obj.save()
        except:
            return 99900, dict_err.get(99900)

        return 0, dict_err.get(0)


class OrderBase(object):

    def get_order_by_trade_id(self, trade_id, state=None):
        try:
            ps = dict(trade_id=trade_id)
            if state is not None:
                ps.update(state=state)
            return Order.objects.select_related("car_wash", "service_price").get(**ps)
        except Order.DoesNotExist:
            pass

    def get_order_by_id(self, id, state=None):
        try:
            ps = dict(id=id)
            if state is not None:
                ps.update(state=state)
            return Order.objects.select_related("car_wash", "service_price").get(**ps)
        except Order.DoesNotExist:
            pass

    def validate_order_info(self, service_price, user_id, count, pay_type):
        assert service_price and user_id and count and pay_type
        assert 1 <= count <= 5
        assert pay_type in (0, 1, 2)

    def check_coupon_can_use(self, coupon, user_id, sale_price, car_wash):
        """
        @note: 检测优惠券是否可用
        """
        if coupon.user_id != user_id:
            return 20202, dict_err.get(20202)
        if coupon.check_is_expiry():
            return 20203, dict_err.get(20203)
        if coupon.car_wash and coupon.car_wash != car_wash:
            return 20204, dict_err.get(20204)
        if coupon.discount >= sale_price:
            return 20205, dict_err.get(20205)
        if coupon.minimum_amount > sale_price:
            return 20206, dict_err.get(20206)

        return 0, dict_err.get(0)

    def generate_order_trade_id(self, pr):
        """
        @note: 生成订单的id，传入不同前缀来区分订单类型
        """
        postfix = '%s' % datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]  # 纯数字
        if pr:
            postfix = '%s%s%02d' % (pr, postfix, random.randint(0, 99))
        return postfix

    @transaction.commit_manually(using=DEFAULT_DB)
    def create_order(self, service_price_id_or_object, user_id, count, pay_type, coupon_id=None, use_user_cash=False, ip=None, page_show_pay_fee=None):
        try:
            from www.cash.interface import UserCashBase

            service_price = service_price_id_or_object if isinstance(service_price_id_or_object, ServicePrice) \
                else ServicePriceBase().get_service_price_by_id(service_price_id_or_object)

            try:
                count = int(count)
                pay_type = int(pay_type)
                self.validate_order_info(service_price, user_id, count, pay_type)   # 检测基本信息
            except:
                transaction.rollback(using=DEFAULT_DB)
                return 99801, dict_err.get(99801)

            car_wash = service_price.car_wash
            total_fee = service_price.sale_price * count
            coupon = None
            discount_fee = 0
            if coupon_id:
                # 检测优惠券信息
                coupon = CouponBase().get_coupon_by_id(coupon_id, user_id)
                if not coupon:
                    transaction.rollback(using=DEFAULT_DB)
                    return 20201, dict_err.get(20201)
                errcode, errmsg = self.check_coupon_can_use(coupon, user_id, service_price.sale_price, car_wash)
                if errcode != 0:
                    transaction.rollback(using=DEFAULT_DB)
                    return errcode, errmsg
                discount_fee = coupon.discount if coupon.coupon_type == 0 else (service_price.sale_price - coupon.discount)

            pay_fee = total_fee - discount_fee
            user_cash = UserCashBase().get_user_cash_by_user_id(user_id)    # 是否使用账户余额
            user_cash_fee = min(pay_fee, float(user_cash.balance)) if use_user_cash else 0
            pay_fee = pay_fee - user_cash_fee
            trade_id = self.generate_order_trade_id(pr="W")
            pay_type = 0 if pay_fee == 0 else pay_type

            if page_show_pay_fee:
                page_show_pay_fee = float(page_show_pay_fee)
                pay_fee = float(pay_fee)

                if abs(page_show_pay_fee - pay_fee) > Decimal(0.001):
                    transaction.rollback(using=DEFAULT_DB)
                    return 20304, dict_err.get(20304)

            ps = dict(trade_id=trade_id, user_id=user_id, service_price=service_price, car_wash=service_price.car_wash,
                      count=count, coupon=coupon, total_fee=total_fee, discount_fee=discount_fee, user_cash_fee=user_cash_fee,
                      pay_fee=pay_fee, pay_type=pay_type, ip=ip)
            order = Order.objects.create(**ps)

            # 不用付费订单直接生成洗车码
            if pay_fee == 0:
                errcode, errmsg = self.order_pay_callback(trade_id, pay_fee, pay_info=u"账户余额付款", order=order)
                if errcode != 0:
                    transaction.rollback(using=DEFAULT_DB)
                    return errcode, errmsg

            transaction.commit(using=DEFAULT_DB)
            return 0, order
        except Exception, e:
            debug.get_debug_detail_and_send_email(e)
            transaction.rollback(using=DEFAULT_DB)
            return 99900, dict_err.get(99900)

    @transaction.commit_manually(using=DEFAULT_DB)
    def order_pay_callback(self, trade_id, payed_fee, pay_info='', order=None):
        '''
        @note: 购物回调函数
        '''
        try:
            from www.tasks import async_send_buy_success_template_msg_by_user_id
            from www.cash.interface import UserCashRecordBase

            errcode, errmsg = 0, dict_err.get(0)
            payed_fee = float(payed_fee)
            order = order

            if (not order) and trade_id.startswith('W'):
                order = self.get_order_by_trade_id(trade_id)
            if not order:
                transaction.rollback(using=DEFAULT_DB)
                return 20301, dict_err.get(20301)

            if order.order_state in (0, ):
                # 付款金额和订单应付金额是否相符
                # if payed_fee != float(order.pay_fee):
                if abs(payed_fee - float(order.pay_fee)) > Decimal(0.001):
                    errcode, errmsg = 20302, dict_err.get(20302)
                order.payed_fee = str(payed_fee)  # 转成string后以便转成decimal
                order.pay_info = pay_info
                order.pay_time = datetime.datetime.now()

                # 更新洗车行订单数
                car_wash = order.car_wash
                car_wash.order_count += 1
                car_wash.save()

                # 修改优惠券状态
                coupon = order.coupon
                if coupon:
                    coupon.state = 2
                    coupon.save()

                # 扣除用户现金账户余额
                if errcode == 0 and order.user_cash_fee > 0:
                    errcode, errmsg = UserCashRecordBase().add_record(order.user_id, order.user_cash_fee, 1, notes=u"购买洗车码")

                codes = []
                if errcode == 0:
                    # 生成洗车码
                    errcode, errmsg = OrderCodeBase().create_order_code(order)
                    if errcode == 0:
                        codes = errmsg
                        errmsg = "ok"

                # 发送邮件
                if payed_fee > 0:
                    user = UserBase().get_user_by_id(order.user_id)
                    title = u'诸位，钱来了'
                    if errcode != 0:
                        title += u"(状态异常，订单号:%s, errcode:%s, errmsg:%s)" % (trade_id, errcode, errmsg)
                    content = u'收到用户「%s」通过「%s」的付款 %.2f 元' % (user.nick, order.get_pay_type_display(), payed_fee)
                    async_send_email("vip@aoaoxc.com", title, content)

                if errcode == 0:
                    # 保存订单信息
                    order.order_state = 1
                    order.save()
                else:
                    transaction.rollback(using=DEFAULT_DB)
                    return errcode, errmsg

                # 异步发送微信模板消息
                if errcode == 0:
                    name = u"%s洗车码" % car_wash.name
                    remark = u""
                    for i, code in enumerate(codes):
                        remark += u"洗车码%s: %s    " % ((i + 1), code)
                    remark += u"在相应洗车行洗车后出示此洗车码即可完成消费"

                    if not settings.LOCAL_FLAG:
                        async_send_buy_success_template_msg_by_user_id.delay(order.user_id, name, remark)

            elif order.order_state < 0:
                errcode, errmsg = 20303, dict_err.get(20303)

            transaction.commit(using=DEFAULT_DB)
            return errcode, errmsg
        except Exception, e:
            debug.get_debug_detail_and_send_email(e)
            transaction.rollback(using=DEFAULT_DB)
            return 99900, dict_err.get(99900)

    def search_orders_for_admin(self, car_wash_name, trade_id, nick, state):
        objs = Order.objects.select_related("car_wash", "service_price").all()

        if trade_id:
            objs = objs.filter(trade_id=trade_id)
            return objs if objs else []

        if car_wash_name:
            objs = objs.filter(car_wash__name__contains=car_wash_name)

        if state is not None:
            objs = objs.filter(order_state=state)

        if nick:
            user = UserBase().get_user_by_nick(nick)
            if user:
                objs = objs.filter(user_id=user.id)
                return objs if objs else []
            else:
                return []

        return objs

    @order_required
    @transaction.commit_manually(using=DEFAULT_DB)
    def refund_order(self, order):
        try:
            from www.cash.interface import UserCashRecordBase

            if order.order_state != 1:
                transaction.rollback(using=DEFAULT_DB)
                return 20307, dict_err.get(20307)

            if not order.check_can_refund():
                transaction.rollback(using=DEFAULT_DB)
                return 20308, dict_err.get(20308)

            # 修改优惠券状态
            coupon = order.coupon
            if coupon:
                coupon.state = 1
                coupon.save()

            # 归还用户现金账户余额
            refund_fee = order.payed_fee + order.user_cash_fee
            if refund_fee > 0:
                errcode, errmsg = UserCashRecordBase().add_record(order.user_id, refund_fee, 0, notes=u"洗车码退款")
                if errcode != 0:
                    transaction.rollback(using=DEFAULT_DB)
                    return errcode, errmsg

            # 更改洗车码状态
            OrderCode.objects.filter(order=order).update(state=2)

            # 更改订单状态
            order.order_state = 10
            order.save()

            # 发送邮件
            user = UserBase().get_user_by_id(order.user_id)
            title = u'有小伙伴遗憾的退款了'
            content = u'用户「%s」申请了「%s」的退款， %.2f元已退还至其账户中' % (user.nick, order.car_wash.name, refund_fee)
            async_send_email("vip@aoaoxc.com", title, content)

            transaction.commit(using=DEFAULT_DB)
            return 0, dict_err.get(0)
        except Exception, e:
            debug.get_debug_detail_and_send_email(e)
            transaction.rollback(using=DEFAULT_DB)
            return 99900, dict_err.get(99900)


    def get_toady_count_group_by_create_time(self):
        '''
        查询当天订单数量 按创建时间分组
        数据格式：
        [09, 15], [10, 23]
        '''
        sql = """
            SELECT DATE_FORMAT(create_time, "%%H"), COUNT(*) 
            FROM www_aoaoxc.car_wash_order 
            WHERE %s <= create_time AND create_time <= %s 
            GROUP BY DATE_FORMAT(create_time, "%%H")
        """
        now = datetime.datetime.now().strftime('%Y-%m-%d')
        
        return raw_sql.exec_sql(sql, [now + ' 00:00:00', now + ' 23:59:59'])


    def get_toady_balance_group_by_create_time(self):
        '''
        查询当天订单金额 按创建时间分组
        数据格式：
        [09, 50.00], [10, 59.00]
        '''
        sql = """
            SELECT DATE_FORMAT(create_time, "%%H"), SUM(total_fee) 
            FROM www_aoaoxc.car_wash_order 
            WHERE %s <= create_time AND create_time <= %s 
            GROUP BY DATE_FORMAT(create_time, "%%H")
        """
        now = datetime.datetime.now().strftime('%Y-%m-%d')

        return raw_sql.exec_sql(sql, [now + ' 00:00:00', now + ' 23:59:59'])


def car_wash_manager_required(func):
    """
    @note: 洗车行管理权限装饰器
    """

    def _decorator(self, car_wash, user, *args, **kwargs):
        if not CarWashManagerBase().check_user_is_cwm(car_wash, user):
            return 20402, dict_err.get(20402)
        return func(self, car_wash, user, *args, **kwargs)
    return _decorator


class OrderCodeBase(object):

    def generate_code(self, car_wash_id):
        """
        @note: 生成洗车码
        """
        code = utils.get_radmon_int(length=10)
        return "%02d%s" % (car_wash_id % 100, code)

    @order_required
    def create_order_code(self, order):
        try:
            try:
                assert order
            except:
                return 99801, dict_err.get(99801)

            count = int(order.count)
            codes = []
            for i in range(count):
                for j in range(3):  # 三次机会，防止重复
                    code = self.generate_code(order.car_wash_id)
                    if not OrderCode.objects.filter(code=code):
                        break
                OrderCode.objects.create(user_id=order.user_id, order=order, car_wash=order.car_wash, code=code)
                codes.append(code)

            return 0, codes
        except Exception, e:
            debug.get_debug_detail_and_send_email(e)
            return 99900, dict_err.get(99900)

    def get_valid_order_codes_by_user_id(self, user_id):
        return OrderCode.objects.select_related("car_wash", "order").filter(user_id=user_id, state=0)

    def get_complete_order_codes_by_user_id(self, user_id):
        return OrderCode.objects.select_related("car_wash", "order").filter(user_id=user_id, state__gt=0)

    def get_order_codes_by_order(self, order):
        return OrderCode.objects.filter(order=order)

    def get_order_code_by_car_wash_and_code(self, car_wash, code):
        try:
            return OrderCode.objects.select_related("car_wash", "order").get(car_wash=car_wash, code=code)
        except OrderCode.DoesNotExist:
            pass

    def get_order_code_by_code(self, code):
        try:
            return OrderCode.objects.select_related("car_wash", "order").get(code=code)
        except OrderCode.DoesNotExist:
            pass

    def get_order_code_by_id(self, code_id):
        try:
            return OrderCode.objects.select_related("car_wash", "order").get(id=code_id)
        except OrderCode.DoesNotExist:
            pass

    @car_wash_manager_required
    @transaction.commit_manually(using=DEFAULT_DB)
    def use_order_code(self, car_wash, user, code, ip=None):
        """
        @note: 使用洗车码
        """
        try:
            from www.cash.interface import CarWashCashRecordBase
            from www.tasks import async_send_use_order_code_template_msg_by_user_id

            order_code = OrderCodeBase().get_order_code_by_code(code)
            if not order_code:
                transaction.rollback(using=DEFAULT_DB)
                return 20305, dict_err.get(20305)

            if order_code.state != 0:   # 判断状态
                transaction.rollback(using=DEFAULT_DB)
                return 20306, dict_err.get(20306)

            car_wash = order_code.car_wash
            # 修改状态
            order_code.state = 1
            order_code.use_time = datetime.datetime.now()
            order_code.operate_user_id = user.id
            order_code.save()

            # 洗车行账户操作
            errcode, errmsg = CarWashCashRecordBase().add_record(car_wash=car_wash, value=order_code.order.service_price.clear_price,
                                                                 operation=0, notes=u"洗车码消费", ip=ip)
            if errcode != 0:
                transaction.rollback(using=DEFAULT_DB)
                return errcode, errmsg

            # 异步发送模板消息
            if not settings.LOCAL_FLAG:
                async_send_use_order_code_template_msg_by_user_id.delay(order_code.user_id, product_type=u"洗车行", name=car_wash.name,
                                                                        time=unicode(datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M'), "utf8"),
                                                                        remark=u"洗车码「%s」已成功使用，欢迎再次购买" % order_code.get_code_display())

            # 异步发送通知邮件
            user = UserBase().get_user_by_id(order_code.user_id)
            title = u'诸位，又有小伙伴去消费了'
            content = u'小伙伴「%s」在洗车行「%s」消费成功，洗车码: %s' % (user.nick, car_wash.name, order_code.get_code_display())
            async_send_email("vip@aoaoxc.com", title, content)

            transaction.commit(using=DEFAULT_DB)
            return 0, dict_err.get(0)
        except Exception, e:
            debug.get_debug_detail_and_send_email(e)
            transaction.rollback(using=DEFAULT_DB)
            return 99900, dict_err.get(99900)

    def search_codes_for_admin(self, car_wash_name, code, nick, state):
        objs = OrderCode.objects.select_related("car_wash", "order").all()

        if code:
            objs = objs.filter(code=code)
            return objs if objs else []

        if car_wash_name:
            objs = objs.filter(car_wash__name__contains=car_wash_name)

        if state is not None:
            objs = objs.filter(state=state)

        if nick:
            user = UserBase().get_user_by_nick(nick)
            if user:
                objs = objs.filter(user_id=user.id)
                return objs if objs else []
            else:
                return []
        return objs


def company_manager_required_for_request(func):
    """
    @note: 过滤器, 公司后台使用
    """
    def _decorator(request, company_id, *args, **kwargs):
        from django.http import HttpResponse, Http404
        from django.shortcuts import render_to_response
        from django.template import RequestContext

        is_cm = CompanyManagerBase().check_user_is_cm(company_id, request.user)
        if not is_cm:
            if request.is_ajax():
                return HttpResponse('{}')
            err_msg = u'权限不足，你还不是公司管理员，如有疑问请联系嗷嗷客服'
            return render_to_response('error.html', locals(), context_instance=RequestContext(request))

        company = CompanyBase().get_company_by_id(company_id)
        if not company:
            raise Http404

        request.company = company
        return func(request, company_id, *args, **kwargs)
    return _decorator


class CompanyBase(object):

    def search_companys_for_admin(self, name):
        objs = Company.objects.all()

        if name:
            objs = objs.filter(name__contains=name)

        return objs

    def get_company_by_id(self, id):
        try:
            ps = dict(id=id)

            return Company.objects.get(**ps)
        except Company.DoesNotExist:
            return ""

    def add_company(self, name):

        if not name:
            return 99800, dict_err.get(99800)
        if Company.objects.filter(name=name):
            return 20501, dict_err.get(20501)

        obj = Company.objects.create(name=name)

        return 0, obj

    def modify_company(self, company_id, name):
        if not name:
            return 99800, dict_err.get(99800)

        obj = self.get_company_by_id(company_id)
        if not obj:
            return 20502, dict_err.get(20502)

        if obj.name != name and Company.objects.filter(name=name):
            return 20501, dict_err.get(20501)

        obj.name = name
        obj.save()
        return 0, dict_err.get(0)

    def get_companys_by_name(self, name=""):
        objs = Company.objects.all()

        if name:
            objs = objs.filter(name__contains=name)

        return objs[:10]

    def update_company_count(self, company_id):
        count = CarWash.objects.filter(state=True, company__id=company_id).count()
        obj = self.get_company_by_id(company_id)
        obj.car_wash_count = count
        obj.save()


    def batch_save_price(self, company_id, service_type_id, sale_price, origin_price, clear_price, sort_num=0):
        
        count = 0
        total = 0

        obj = self.get_company_by_id(company_id)
        if not obj:
            return 20502, dict_err.get(20502)

        for car_wash in CarWash.objects.filter(company__id=company_id):

            total += 1

            flag, msg = ServicePriceBase().add_service_price(car_wash, service_type_id, sale_price, origin_price, clear_price, sort_num)
            
            if flag == 0:
                count += 1

        return 0, u"共处理[ %s ]家洗车行,成功[ %s ]家" % (total, count)


    def batch_save_info(self, company_id, business_hours, lowest_sale_price, lowest_origin_price, imgs, des, note):
        
        count = 0
        total = 0

        obj = self.get_company_by_id(company_id)
        if not obj:
            return 20502, dict_err.get(20502)

        for car_wash in CarWash.objects.filter(company__id=company_id):

            total += 1

            if business_hours:
                car_wash.business_hours = business_hours
            if lowest_sale_price:
                car_wash.lowest_sale_price = lowest_sale_price
            if lowest_origin_price:
                car_wash.lowest_origin_price = lowest_origin_price
            if imgs:
                car_wash.imgs = imgs
            if des:
                car_wash.des = des
            if note:
                car_wash.note = note

            try:
                car_wash.save()
                count += 1
            except Exception:
                continue

        return 0, u"共处理[ %s ]家洗车行,成功[ %s ]家" % (total, count)



class CompanyManagerBase(object):

    def get_cm_by_user_id(self, user_id):
        """
        @note: 获取用户管理的第一个洗车行，用于自动跳转到管理的洗车行
        """
        cms = list(CompanyManager.objects.select_related("company").filter(user_id=user_id))
        if cms:
            return cms[0]

    def check_user_is_cm(self, company_id, user):
        """
        @note: 判断用户是否是某个洗车行管理员
        """
        if isinstance(user, (str, unicode)):
            user = UserBase().get_user_by_id(user)

        cm = CompanyManager.objects.filter(company__id=company_id, user_id=user.id)

        return True if (cm or user.is_staff()) else False

    def add_company_manager(self, company_id, user_id):
        if user_id and not UserBase().get_user_login_by_id(user_id):
            return 99600, dict_err.get(99600)

        if CompanyManager.objects.filter(user_id=user_id, company__id=company_id):
            return 20401, dict_err.get(20401)

        cm = CompanyManager.objects.create(user_id=user_id, company_id=company_id)
        return 0, cm

    def search_managers_for_admin(self, company_name):
        objs = CompanyManager.objects.select_related("company").all()

        if company_name:
            objs = objs.filter(company__name__contains=company_name)

        return objs

    def get_manager_by_id(self, manager_id):
        try:
            return CompanyManager.objects.select_related("company").get(id=manager_id)
        except CompanyManager.DoesNotExist:
            pass

    def delete_company_manager(self, manager_id):
        if not manager_id:
            return 99800, dict_err.get(99800)

        try:
            CompanyManager.objects.get(id=manager_id).delete()
        except Exception:
            return 99900, dict_err.get(99900)

        return 0, dict_err.get(0)
