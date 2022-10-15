from multiprocessing import context
from urllib import response
from django.shortcuts import render, redirect

from django.http import HttpResponse, JsonResponse
from marketplace.models import Cart
from marketplace.context_processors import get_cart_amounts
from orders.forms import OrderForm
from orders.models import Order, OrderedFood, Payment
import simplejson as json # install simplejson via pip
from .utils import generate_order_number
from accounts.utils import send_notification
from django.contrib.auth.decorators import login_required


@login_required(login_url='login')
def place_order(request):
    # To have access to the cart items
    cart_items = Cart.objects.filter(user=request.user).order_by('created_at')
    cart_count = cart_items.count()
    if cart_count <=0:
        return redirect('marketplace')
    
    subtotal = get_cart_amounts(request)['subtotal']
    total_tax = get_cart_amounts(request)['tax']
    grand_total = get_cart_amounts(request)['grand_total']
    tax_data = get_cart_amounts(request)['tax_dict']

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            order = Order()
            order.first_name = form.cleaned_data['first_name']
            order.last_name = form.cleaned_data['last_name']
            order.phone = form.cleaned_data['phone']
            order.email = form.cleaned_data['email']
            order.address = form.cleaned_data['address']
            order.country = form.cleaned_data['country']
            order.state = form.cleaned_data['state']
            order.city = form.cleaned_data['city']
            order.pin_code = form.cleaned_data['pin_code']
            order.user = request.user
            order.total = grand_total
            # convert tax data to json format to avoid errors (Decimal) due to serialization
            # But when we will retrive that from db, we will use json load
            order.tax_data = json.dumps(tax_data) 
            order.total_tax = total_tax
            order.payment_method = request.POST['payment_method']

            order.save() # order id/pk is generated once the order is saved
            order.order_number = generate_order_number(order.id) #order.id is the primary key of order
            order.save()
            context = {
                'order':order,
                'cart_items': cart_items,
            }
            return render(request,'orders/place_order.html',context)
        else:
            print(form.errors)
    else:
        pass
    return render(request,'orders/place_order.html')

@login_required(login_url='login')
def payments(request):
    # Check if the request is AJAX or not
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and request.method == 'POST':
         # Store the payment details in the Payment Model

        # Store payment details in DB
        order_number = request.POST.get('order_number')
        transaction_id = request.POST.get('transaction_id')
        payment_method = request.POST.get('payment_method')
        status = request.POST.get('status')

        #  Get order having the order number
        order = Order.objects.get(user=request.user, order_number=order_number)
        # payment model
        payment = Payment(
            user = request.user,
            transaction_id = transaction_id,
            payment_method = payment_method,
            amount = order.total,
            status = status
        )

        # save the payment model now
        payment.save()


        # Update the ORDER MODEL
        order.payment = payment
        order.is_ordered = True
        order.save()

        # Move the CART ITEMS to ORDERED FOOD MODEL
        cart_items = Cart.objects.filter(user=request.user)
        for item in cart_items:
            ordered_food = OrderedFood()
            ordered_food.order = order
            ordered_food.payment = payment
            ordered_food.user = request.user
            ordered_food.fooditem = item.fooditem
            ordered_food.quantity = item.quantity
            ordered_food.price = item.fooditem.price
            ordered_food.amount = item.fooditem.price * item.quantity # total amount
            ordered_food.save()
        
        # SEND ORDER CONFIRMATION EMAIL TO THE CUSTOMER
        mail_subject = 'Thanks for Ordering with Us. Your Order Has Been Recieved!'
        mail_template = 'orders/order_confirmation_email.html'
        context = {
            'user': request.user,
            'order': order,
            'to_email': order.email,
        }

        send_notification(mail_subject, mail_template, context)
        

        # SEND ORDERED RECEIVED EMAIL TO THE VENDOR
        mail_subject = 'You have received a new order.'
        mail_template = 'orders/new_order_received.html'
        to_emails = []
        for i in cart_items:
            if i.fooditem.vendor.user.email not in to_emails:
                to_emails.append(i.fooditem.vendor.user.email)
            
            context = {

                'order': order,
                'to_email': to_emails,

            }
        
       

        send_notification(mail_subject, mail_template, context)

        # CLEAR THE CART IF THE PAYMENT IS SUCCESSFUL
        cart_items.delete()


        # RETURN BACK TO AJAX WITH THE STATUS OF EITHER SUCCESS OR FAILURE
        response = {
            'order_number': order_number,
            'transaction_id': transaction_id,
        }
        return JsonResponse(response)

    return HttpResponse('Payment Page here!')


def order_complete(request):
    order_number = request.GET.get('order_no')
    transaction_id = request.GET.get('trans_id')

    try:
        order = Order.objects.get(order_number=order_number,payment__transaction_id=transaction_id, is_ordered=True)
        ordered_food = OrderedFood.objects.filter(order=order)

        # calculte order info to be sent to the completion page
        subtotal = 0
        for item in ordered_food:
            subtotal += (item.price * item.quantity)
        
        tax_data = json.loads(order.tax_data)

        context = {
            'order': order,
            'ordered_food': ordered_food,
            'subtotal': subtotal,
            'tax_data': tax_data,
        }
        return render(request, 'orders/order_complete.html',context)
    except:
        return redirect('home')
    